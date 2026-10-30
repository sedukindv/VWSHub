"""Live and XMEye archive transport. No default credentials, no recording duplication.

The single authenticated DVRIP/DownloadStart flow preserves XM channel routing.
Only recorder-confirmed files are exposed; all media routes apply group + archive ACL.
"""
from __future__ import annotations
import atexit
import json
import logging
import math
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from flask import Blueprint, Response, current_app, jsonify, request, send_from_directory, session, stream_with_context
from werkzeug.utils import secure_filename
try:
    from dvrip import DVRIPCam
except ImportError:
    DVRIPCam = None

log=logging.getLogger('vwshub.media')
OK_CODES={100,150,515}
DVRIP_HEADER=struct.Struct('BB2xII2xHI')
def runtime(): return current_app.extensions['vwshub']
def get_camera(cam_id): return runtime().get_camera(cam_id)
def dec_pwd(value): return runtime().dec_pwd(value)
def resources():
    settings=runtime().settings()
    configured=settings.get('resources',{})
    return {'max_live_streams':int(configured.get('max_live_streams',16)),
            'max_archive_streams':int(configured.get('max_archive_streams',4)),
            'archive_buffer_mb':int(configured.get('archive_buffer_mb',16)),
            'archive_idle_seconds':int(configured.get('archive_idle_seconds',180)),
            'ffmpeg_threads':int(configured.get('ffmpeg_threads',2))}

def hardware_event(rt,event,camera,**details):
    journal=getattr(rt,'hardware',None)
    if journal:journal.record(event,camera,**details)

def build_rtsp_live_url(cam, stream_type="main"):
    proto = cam.get("protocol", "dvrip")
    ip = cam["ip"]
    user = cam.get("username", "")
    pwd = dec_pwd(cam.get("password", ""))
    user_enc = quote(user, safe="")
    pass_enc = quote(pwd, safe="")
    rtsp_port = int(cam.get("rtsp_port", 554))

    if proto == "dvrip":
        channel = int(cam.get("channel", 0))
        s = 0 if stream_type == "main" else 1
        return (f"rtsp://{user_enc}:{pass_enc}@{ip}:{rtsp_port}/"
                f"user={user}&password={pwd}"
                f"&channel={channel + 1}&stream={s}.sdp?real_stream")
    path = cam.get("rtsp_path", "").strip()
    if path and not path.startswith("/"): path = "/" + path
    host=cam.get('rtsp_host') or ip
    if ':' in host:host='['+host+']'
    return f"rtsp://{user_enc}:{pass_enc}@{host}:{rtsp_port}{path}"

def open_dvr_connection(cam,password,on_open=None):
    if DVRIPCam is None: raise RuntimeError('Установите DVRIP-зависимость из requirements.txt')
    dvr=DVRIPCam(cam['ip'],user=cam.get('username',''),password=password,port=int(cam.get('port',34567)))
    sock=None
    try:
        # python-dvr sets its timeout after connect(). Establish the identical TCP
        # transport with a timeout first so an offline host cannot pin a worker.
        if dvr.socket is None:
            sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM);sock.settimeout(10)
            dvr.socket=sock;dvr.socket_send=dvr.tcp_socket_send;dvr.socket_recv=dvr.tcp_socket_recv;dvr.timeout=10
        if on_open is not None and on_open(dvr) is False:raise ConnectionAbortedError('Сеанс отменён')
        if sock is not None:sock.connect((cam['ip'],int(cam.get('port',34567))))
        if not dvr.login():raise ConnectionError('Регистратор отклонил авторизацию')
        dvr.timeout=10
        try:dvr.socket.settimeout(10)
        except Exception:pass
        return dvr
    except Exception:
        try:dvr.close()
        except Exception:pass
        if sock is not None:
            try:sock.close()
            except Exception:pass
        raise

def dvr_connect(cam):return open_dvr_connection(cam,dec_pwd(cam.get('password','')))

class LiveManager:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.streams = {}
        self.stop_event=threading.Event()

    def _stop_locked(self, key):
        item = self.streams.pop(key, None)
        if not item: return
        proc = item.get("process")
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=2)
        try: item["log_file"].close()
        except Exception: pass
        shutil.rmtree(item["directory"], ignore_errors=True)

    def stop(self, cam_id, stream):
        with self.lock: self._stop_locked((cam_id, stream))

    def release(self, cam_id, stream, consumer):
        """Release this browser's lease; other browsers keep their shared stream."""
        with self.lock:
            item = self.streams.get((cam_id, stream))
            if not item: return
            leases = item.setdefault("leases", {})
            leases.pop(consumer, None)
            cutoff = time.monotonic() - 30
            if not any(seen > cutoff for seen in leases.values()):
                self._stop_locked((cam_id, stream))

    def reap(self):
        """Bound abandoned FFmpeg processes even when a browser closes abruptly."""
        while not self.stop_event.wait(10):
            with self.lock:
                cutoff = time.monotonic() - 30
                for key, item in list(self.streams.items()):
                    if not any(seen > cutoff for seen in item.get("leases", {}).values()):
                        self._stop_locked(key)

    def stop_all(self):
        with self.lock:
            for k in list(self.streams): self._stop_locked(k)

    def ensure(self, cam_id, stream, consumer="legacy"):
        if stream not in ("main", "sub"): raise ValueError("Поток: main или sub")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(cam_id)): raise ValueError("Некорректный идентификатор камеры")
        cam = get_camera(cam_id)
        if not cam: raise ValueError("Камера не найдена")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg: raise RuntimeError("FFmpeg не установлен")

        key = (cam_id, stream)
        with self.lock:
            for expired,item in list(self.streams.items()):
                if item['process'].poll() is not None:self._stop_locked(expired)
            ex = self.streams.get(key)
            if ex and ex["process"].poll() is None:
                ex.setdefault("leases", {})[consumer] = time.monotonic()
                return ex
            if ex: self._stop_locked(key)

            if len(self.streams)>=resources()["max_live_streams"]: raise RuntimeError("Достигнут лимит одновременных потоков сервера")
            directory = self.root / f"{cam_id}_{stream}"
            shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)
            log_file = open(directory / "ffmpeg.log", "ab", buffering=0)

            cmd = [
                ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "warning",
                "-rtsp_transport", "tcp", "-i", build_rtsp_live_url(cam, stream),
                "-map", "0:v:0", "-an", "-c:v", "copy",
                "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
                "-hls_delete_threshold", "2",
                "-hls_flags", "delete_segments+append_list+omit_endlist+independent_segments",
                "-hls_segment_filename", str(directory / "seg_%06d.ts"),
                str(directory / "index.m3u8"),
            ]
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log_file)
            item = {"process": proc, "directory": directory, "log_file": log_file, "leases": {consumer: time.monotonic()}}
            self.streams[key] = item
            return item

def normalize_time(v: str) -> str:
    v = (v or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try: return datetime.strptime(v, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError: continue
    raise ValueError("Время: ГГГГ-ММ-ДД ЧЧ:ММ[:СС]")

def parse_times_from_path(path: str):
    base = re.split(r"[\\/]", path)[-1]
    date_match = re.search(r"(20\d{2})[-_/]?(\d{2})[-_/]?(\d{2})", path)
    tm = re.search(r"(?P<h1>\d{2})[._:-](?P<m1>\d{2})[._:-](?P<s1>\d{2})-(?P<h2>\d{2})[._:-](?P<m2>\d{2})[._:-](?P<s2>\d{2})", base)
    if not date_match or not tm: return None, None
    try:
        y, mo, d = (int(date_match.group(i)) for i in (1, 2, 3))
        v = {k: int(x) for k, x in tm.groupdict().items()}
        st = datetime(y, mo, d, v["h1"], v["m1"], v["s1"])
        en = datetime(y, mo, d, v["h2"], v["m2"], v["s2"])
    except ValueError: return None, None
    if en < st: en += timedelta(days=1)
    return st.strftime("%Y-%m-%d %H:%M:%S"), en.strftime("%Y-%m-%d %H:%M:%S")

def dvrip_channel_from_path(path: str):
    """Infer the zero-based DVR channel from standard /YYYY-MM-DD/00N/ paths."""
    normalized = str(path or "").replace("\\", "/")
    match = re.search(r"(?:^|/)(?:20\d{2}[-_/]?\d{2}[-_/]?\d{2})/(\d{3})(?:/|$)", normalized)
    if not match:
        return None
    try:
        folder_channel = int(match.group(1))
    except (ValueError, TypeError):
        return None
    return folder_channel - 1 if folder_channel >= 1 else None


def normalize_recordings(records, channel=0):
    """Validate, sort and deduplicate recorder file ranges without filling gaps."""
    normalized, seen = [], set()
    for record in records:
        if not isinstance(record, dict):
            continue
        path = record.get("FilePath") or record.get("FileName") or record.get("Path") or record.get("Name")
        if not isinstance(path, str) or not path.strip() or len(path) > 2048 or "\x00" in path:
            continue
        fallback = None
        times = []
        for key, index in (("BeginTime", 0), ("EndTime", 1)):
            try:
                value = normalize_time(record.get(key))
            except (ValueError, TypeError, AttributeError):
                if fallback is None:
                    fallback = parse_times_from_path(path)
                value = fallback[index]
            times.append(value)
        start, end = times
        if not start or not end or start >= end:
            continue
        identity = (path, start, end)
        if identity in seen:
            continue
        seen.add(identity)
        # Keep complete ranges, including files crossing query boundaries;
        # callers can clip these to their displayed search window.
        path_channel = dvrip_channel_from_path(path)
        # A path channel is authoritative when its directory encodes /001/,
        # /002/, ... . If it does not, use the channel used for this OPFileQuery.
        # Some XM-derived firmwares return a stale/default Channel=0 field in
        # each file item even after a channel-specific query; trusting that field
        # marks every file as CH1 and makes the archive UI select the first camera.
        actual_channel = path_channel if path_channel is not None else channel
        normalized.append({"FileName": path, "FilePath": path,
                           "BeginTime": start, "EndTime": end,
                           "Channel": actual_channel})
    return sorted(normalized, key=lambda row: (row["BeginTime"], row["EndTime"], row["FilePath"]))


def _group_recordings(records, gap_seconds=300):
    if not records: return []
    parsed = []
    for r in records:
        try:
            bt = datetime.strptime(r["BeginTime"], "%Y-%m-%d %H:%M:%S")
            et = datetime.strptime(r["EndTime"], "%Y-%m-%d %H:%M:%S")
        except Exception: continue
        if et <= bt: continue
        parsed.append((bt, et, r))
    if not parsed: return []

    parsed.sort(key=lambda x: x[0])
    groups = []
    cur_bt, cur_et, items = parsed[0][0], parsed[0][1], [parsed[0][2]]
    for bt, et, r in parsed[1:]:
        if (bt - cur_et).total_seconds() <= gap_seconds:
            if et > cur_et: cur_et = et
            items.append(r)
        else:
            groups.append((cur_bt, cur_et, items))
            cur_bt, cur_et, items = bt, et, [r]
    groups.append((cur_bt, cur_et, items))

    result = []
    for bt, et, items in groups:
        result.append({
            "BeginTime": bt.strftime("%Y-%m-%d %H:%M:%S"),
            "EndTime":   et.strftime("%Y-%m-%d %H:%M:%S"),
            "Files":     len(items),
            # A group can span short recording gaps. Keep its actual intervals
            # so the timeline does not paint unavailable footage as recorded.
            "Intervals": [{"BeginTime": r["BeginTime"], "EndTime": r["EndTime"]} for r in items],
            "FileName": items[0].get("FileName"),
            "FilePath": items[0].get("FileName"),
            "Channel":  items[0].get("Channel", 0),
        })
    return result

def recv_exact(sock, size: int, cancel=None, max_idle_timeouts: int = 18) -> bytes:
    """Read an exact DVRIP payload without losing partial data on socket timeouts."""
    data = bytearray()
    idle_timeouts = 0
    while len(data) < size:
        if cancel is not None and cancel.is_set():
            raise ConnectionAbortedError("Чтение архива отменено")
        try:
            part = sock.recv(size - len(data))
        except socket.timeout:
            idle_timeouts += 1
            # DVRIP archive data is bursty; preserve any partial header/payload and
            # allow several idle windows before reporting a real stalled connection.
            if idle_timeouts >= max_idle_timeouts:
                raise TimeoutError("Регистратор слишком долго не передавал данные архива")
            continue
        if not part:
            raise ConnectionError("Регистратор закрыл соединение во время чтения архива")
        data.extend(part)
        idle_timeouts = 0
    return bytes(data)


def _dvrip_read_packet(sock, cancel=None, max_idle_timeouts=18):
    header = recv_exact(sock, 20, cancel=cancel, max_idle_timeouts=max_idle_timeouts)
    magic, version, session_id, sequence, msg_id, data_len = DVRIP_HEADER.unpack(header)
    if magic != 255:
        raise ConnectionError("Некорректный заголовок DVRIP при чтении архива")
    if data_len < 0 or data_len > 64 * 1024 * 1024:
        raise ConnectionError(f"Некорректная длина DVRIP-пакета: {data_len}")
    payload = recv_exact(sock, data_len, cancel=cancel, max_idle_timeouts=max_idle_timeouts) if data_len else b""
    return msg_id, payload


def _dvrip_json_reply(payload: bytes):
    if not payload:
        return None
    try:
        return json.loads(payload.rstrip(b"\x00\x0a").decode("utf-8", errors="strict"))
    except (ValueError, UnicodeDecodeError):
        return None


def dvrip_stream_chunks(cam, msg_id: int, payload: dict, cancel=None):
    """Compatibility reader for firmwares that stream on the control socket.

    A DVRIP frame's message ID matters: media is 1422/1426 and EOF is 1423.
    Do not terminate merely because an unrelated response happens to have an
    empty payload, which caused playback to stop on some recorders.
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\x0a\x00"
    packet = DVRIP_HEADER.pack(255, 0, int(cam.session), int(cam.packet_count), msg_id, len(body)) + body
    cam.busy.acquire()
    try:
        cam.socket_send(packet)
        while cancel is None or not cancel.is_set():
            reply_id, chunk = _dvrip_read_packet(cam.socket, cancel=cancel, max_idle_timeouts=getattr(cam,'archive_idle_timeouts',18))
            if reply_id == 1423:  # PLAY_EOF
                return
            if reply_id in (1422, 1426):  # PLAY_DATA / DOWNLOAD_DATA
                if not chunk:
                    return
                yield chunk
                continue
            reply = _dvrip_json_reply(chunk)
            if isinstance(reply, dict) and reply.get("Ret") not in (None, *OK_CODES):
                raise RuntimeError(f"Регистратор прервал чтение архива (Ret={reply.get('Ret')})")
            # Skip claim/start acknowledgements and other control packets.
    finally:
        cam.busy.release()


def dvrip_playback_chunks(cam, file_path: str, start: str, end: str, mode="files", channel=0, cancel=None):
    """Read archive through the recorder's established single-socket DVRIP flow.

    WebVMS_Frigate_ArchiveTimeline used DownloadStart on the authenticated
    control socket. The dual-socket Start flow introduced in a later revision
    could be accepted by some XM firmware while delivering channel-1 data or
    stopping shortly after playback began. Keep the proven transport, but parse
    DVRIP message IDs so control acknowledgements are never sent to FFmpeg.

    Channel selection is made explicit in both ways supported by the firmware:
    the exact OPFileQuery path (ByName) and the zero-based Channel parameter.
    If the path encodes a channel, it must agree with the selected camera.
    """
    if not file_path:
        raise ValueError("Для воспроизведения архива требуется точный путь файла записи")
    try:
        selected_channel = int(channel)
    except (TypeError, ValueError):
        raise ValueError("Некорректный номер канала архива") from None
    file_channel = dvrip_channel_from_path(file_path)
    if file_channel is not None and file_channel != selected_channel:
        raise ValueError(
            f"Файл архива принадлежит каналу {file_channel + 1}, "
            f"а выбрана камера канала {selected_channel + 1}"
        )

    params = {
        "PlayMode": "ByName",
        "FileName": file_path,
        "StreamType": 0,
        "Value": 0,
        "TransMode": "TCP",
        "Channel": selected_channel,
    }
    times = {"StartTime": start, "EndTime": end}
    # Keep the payload envelope identical to python-dvr / the previously
    # working ArchiveTimeline implementation. The authenticated session ID is
    # already in the 20-byte DVRIP header; duplicating it as a JSON field is not
    # part of the legacy protocol and can trigger OEM firmware quirks.
    claim_payload = {
        "Name": "OPPlayBack",
        "OPPlayBack": {"Action": "Claim", "Parameter": params, **times},
    }
    start_payload = {
        "Name": "OPPlayBack",
        "OPPlayBack": {"Action": "DownloadStart", "Parameter": params, **times},
    }
    stop_payload = {
        "Name": "OPPlayBack",
        "OPPlayBack": {"Action": "DownloadStop", "Parameter": params, **times},
    }

    # Claim and transfer must use the same authenticated DVRIP connection for
    # the known-working firmware family. This avoids the short-lived stream
    # observed when a second, unauthenticated TCP connection was used for data.
    claim_reply = cam.send(1424, claim_payload)
    if not isinstance(claim_reply, dict) or claim_reply.get("Ret") not in OK_CODES:
        raise RuntimeError(f"Регистратор не разрешил архивный сеанс: {claim_reply!r}")
    try:
        yield from dvrip_stream_chunks(cam, 1420, start_payload, cancel=cancel)
    finally:
        if cancel is None or not cancel.is_set():
            try:
                cam.send(1420, stop_payload)
            except Exception:
                pass

def _valid_annexb_nal(payload: bytes, codec: str) -> bool:
    """Reject malformed H.264/H.265 NAL headers before they reach FFmpeg.

    A number of XM-derived recorders inject a 127-byte service block into the
    H.265 archive every ~2 seconds, wrapped as an ordinary delta frame. Its
    first HEVC NAL claims layer_id=32 in a single-layer stream. Some decoders
    treat that as fatal and stop exactly when the block arrives.
    """
    if payload.startswith(b"\x00\x00\x00\x01"):
        offset = 4
    elif payload.startswith(b"\x00\x01"):
        # Not a legal three-byte Annex-B start code; don't accept accidental data.
        return False
    elif payload.startswith(b"\x00\x00\x01"):
        offset = 3
    else:
        return False
    if codec == "h264":
        if len(payload) <= offset:
            return False
        header = payload[offset]
        nal_type = header & 0x1F
        return not (header & 0x80) and 1 <= nal_type <= 23
    if codec in ("hevc", "h265"):
        if len(payload) <= offset + 1:
            return False
        first, second = payload[offset], payload[offset + 1]
        layer_id = ((first & 0x01) << 5) | (second >> 3)
        temporal_id_plus1 = second & 0x07
        nal_type = (first >> 1) & 0x3F
        return not (first & 0x80) and layer_id == 0 and temporal_id_plus1 >= 1 and nal_type <= 40
    return False


def iter_dvr_video_frames(chunks, metadata=None):
    buffer = bytearray()
    codec_format = None
    waiting_for_keyframe = True
    max_frame_size = 64 * 1024 * 1024
    for chunk in chunks:
        if chunk: buffer.extend(chunk)
        while True:
            marker = buffer.find(b"\x00\x00\x01")
            if marker < 0:
                if len(buffer) > 3: del buffer[:-3]
                break
            if marker > 0: del buffer[:marker]
            if len(buffer) < 4: break
            frame_type = buffer[3]
            if frame_type in (0xFC, 0xFE):
                header_size = 16
                if len(buffer) < header_size: break
                payload_size = struct.unpack_from("<I", buffer, 12)[0]
                frame_fps = buffer[5]
                frame_datetime = struct.unpack_from("<I", buffer, 8)[0]
                media_code = buffer[4] & 0x0F
                if media_code == 2: discovered_format = "h264"
                elif media_code == 3: discovered_format = "hevc"
                elif media_code == 1: discovered_format = "m4v"
                else: discovered_format = None
            elif frame_type == 0xFD:
                header_size = 8
                if len(buffer) < header_size: break
                payload_size = struct.unpack_from("<I", buffer, 4)[0]
                discovered_format = codec_format
            elif frame_type in (0xFA, 0xF9):
                header_size = 8
                if len(buffer) < header_size: break
                payload_size = struct.unpack_from("<H", buffer, 6)[0]
                discovered_format = None
            else:
                del buffer[0]; continue
            if payload_size < 0 or payload_size > max_frame_size:
                del buffer[0]; continue
            total = header_size + payload_size
            if len(buffer) < total: break
            payload = bytes(buffer[header_size:total])
            del buffer[:total]
            if frame_type in (0xFC, 0xFE) and discovered_format:
                codec_format = discovered_format
                waiting_for_keyframe = False
                if metadata is not None and not metadata:
                    # OpenIPC/python-dvr: keyframe wrapper is BBBBII after
                    # the marker: media,FPS,width/8,height/8,datetime,length.
                    if 1 <= frame_fps <= 120:
                        metadata["fps"] = frame_fps
                    packed = frame_datetime
                    try:
                        stamp = datetime(2000 + ((packed >> 26) & 0x3F),
                                         (packed >> 22) & 0x0F, (packed >> 17) & 0x1F,
                                         (packed >> 12) & 0x1F, (packed >> 6) & 0x3F,
                                         packed & 0x3F)
                        metadata["start_time"] = stamp.strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass
            if frame_type == 0xFD and codec_format:
                discovered_format = codec_format
            if not payload or discovered_format is None: continue
            # Every valid DVRIP video payload is an Annex-B NAL. Filter corrupt
            # wrappers/service blocks here so one bad frame cannot stop the MP4
            # decoder in the browser a couple seconds after playback starts.
            if not _valid_annexb_nal(payload, discovered_format):
                continue
            if waiting_for_keyframe: continue
            yield discovered_format, payload


def iter_dvr_audio_frames(chunks, metadata=None):
    """Extract only verified G.711 A-law NETIP audio payloads.

    The format follows python-dvr.reassemble_bin_payload (0x1FA, media0x0E).
    No audio is extracted or transcoded unless the caller explicitly requests it.
    """
    data=bytearray()
    for chunk in chunks:
        data.extend(chunk or b'')
        while True:
            marker=data.find(b'\x00\x00\x01')
            if marker<0:
                if len(data)>3:del data[:-3]
                break
            if marker:del data[:marker]
            if len(data)<8:break
            kind=data[3]
            if kind in (0xFC,0xFE):
                if len(data)<16:break
                header,size=16,struct.unpack_from('<I',data,12)[0]
                if metadata is not None and not metadata:
                    packed=struct.unpack_from('<I',data,8)[0]
                    try:metadata['start_time']=datetime(2000+((packed>>26)&63),(packed>>22)&15,(packed>>17)&31,(packed>>12)&31,(packed>>6)&63,packed&63).strftime('%Y-%m-%d %H:%M:%S')
                    except ValueError:pass
            elif kind==0xFD:header,size=8,struct.unpack_from('<I',data,4)[0]
            elif kind in (0xFA,0xF9):header,size=8,struct.unpack_from('<H',data,6)[0]
            else:del data[0];continue
            if size>64*1024*1024:del data[0];continue
            if len(data)<header+size:break
            codec,rate=data[4],data[5]
            payload=bytes(data[header:header+size]);del data[:header+size]
            if kind!=0xFA or not payload:continue
            if codec!=0x0E or rate not in (0,8):
                raise ValueError('Формат архивного звука не поддерживается (доступен G.711 A-law 8 кГц)')
            yield 'alaw',payload


class MediaService:
    def __init__(self, app, rt):
        self.runtime=rt
        self.lock=threading.RLock()
        self.active_archives=0
        self.files={}
        self.audio_cache={}
        self.operations={}
        self.cancelled={}
        self.live=LiveManager(Path(app.config.get('LIVE_ROOT',rt.store.base_dir/'live')))
        threading.Thread(target=self.live.reap,name='vwshub-live-reaper',daemon=True).start()
        atexit.register(self.stop_all)

    def stop_all(self):
        self.live.stop_event.set();self.live.stop_all()
        with self.lock:operations=list(self.operations.values())
        for operation in operations:operation['cancel']()

    def stats(self):
        with self.lock:return {'live_streams':len(self.live.streams),'archive_streams':self.active_archives}

    def reserve(self, limit):
        with self.lock:
            if self.active_archives>=limit:return False
            self.active_archives+=1
            return True

    def release(self):
        with self.lock:self.active_archives=max(0,self.active_archives-1)

    def cancel_operation(self, owner, play_id, cam_id):
        key=(owner,play_id)
        with self.lock:
            self.cancelled[key]=time.monotonic()
            operation=self.operations.get(key)
            if len(self.cancelled)>4096:self.cancelled={k:t for k,t in self.cancelled.items() if t>time.monotonic()-300}
        if operation and operation['camera']==str(cam_id):operation['cancel']()

    def remember(self,cam_id,records):
        with self.lock:
            now=time.monotonic()
            for record in records:self.files[(str(cam_id),record['FilePath'])]=(now,record)
            if len(self.files)>20000:self.files={key:value for key,value in self.files.items() if value[0]>now-300}

    def query_files(self,cam,start,end):
        began=time.monotonic();dvr=None
        try:
            dvr=dvr_connect(cam)
            raw=dvr.list_local_files(start,end,'h264',channel=int(cam.get('channel',0)))
            if not isinstance(raw,(list,tuple)):raise RuntimeError('Регистратор вернул некорректный список записей')
            channel=int(cam.get('channel',0))
            records=[r for r in normalize_recordings(raw,channel) if r['Channel']==channel]
            self.remember(cam['id'],records)
            hardware_event(self.runtime,'archive.list',cam,records=len(records),start=start,end=end,duration_ms=round((time.monotonic()-began)*1000))
            return records
        except Exception as exc:
            hardware_event(self.runtime,'archive.list_failed',cam,level='error',error_type=type(exc).__name__,duration_ms=round((time.monotonic()-began)*1000));raise
        finally:
            if dvr is not None:dvr.close()

    def resolve(self,cam,start,end,path=''):
        """Bind every file to the selected camera; a viewer cannot inject CH1 paths."""
        channel=int(cam.get('channel',0))
        if path:
            encoded=dvrip_channel_from_path(path)
            if encoded is not None and encoded!=channel:raise ValueError('Файл принадлежит другому каналу регистратора')
            with self.lock:cached=self.files.get((str(cam['id']),path))
            if cached and cached[0]>time.monotonic()-300:
                records=[cached[1]]
            else:
                records=[r for r in self.query_files(cam,start,end) if r['FilePath']==path]
        else:records=self.query_files(cam,start,end)
        matches=[r for r in records if r['BeginTime']<end and r['EndTime']>start]
        if not matches:raise ValueError('Нет файла выбранного канала в этом диапазоне. Обновите архив.')
        return sorted(matches,key=lambda r:(r['BeginTime'],r['FilePath']))

    def audio_capabilities(self,cam,refresh=False):
        key=str(cam['id'])
        with self.lock:cached=self.audio_cache.get(key)
        if not refresh and cached and cached[0]>time.monotonic()-30:return cached[1]
        dvr=dvr_connect(cam)
        try:
            config=dvr.get_encode_info()
            if isinstance(config,dict):config=config.get('Simplify.Encode',config)
            channel=int(cam.get('channel',0))
            item=config[channel] if isinstance(config,list) and 0<=channel<len(config) else config if isinstance(config,dict) and channel==0 else {}
            main=item.get('MainFormat',{}) if isinstance(item,dict) else {}
            enabled=main.get('AudioEnable') is True or main.get('AudioEnable')==1
            audio=main.get('Audio',{})
            codec=str(audio.get('Compression',audio.get('EncodeType',''))).lower().replace('.','').replace('_','').replace('-','') if isinstance(audio,dict) else ''
            # Simplify.Encode omits the codec on some XM firmware. A confirmed
            # AudioEnable permits an explicit attempt; the NETIP audio header is
            # still checked before any byte is played. An explicitly unsupported
            # codec stays disabled rather than silently mis-decoding it.
            supported=enabled and codec in {'','g711a','g711alaw','alaw','g711'}
            result={'enabled':enabled,'supported':supported,'codec':'g711a' if codec else None,
                    'reason':'Звук выключен на устройстве' if not enabled else 'Микрофон включён; формат архивного звука проверяется при запуске' if supported else 'Формат архивного звука не поддерживается'}
        except Exception:
            result={'enabled':False,'supported':False,'codec':None,'reason':'Устройство не подтвердило включённый микрофон'}
        finally:dvr.close()
        with self.lock:self.audio_cache[key]=(time.monotonic(),result)
        return result


def _write_all(stream, payload, cancel=None):
    """FileIO on an unbuffered pipe may accept only part of a large frame."""
    pending=memoryview(payload)
    while pending:
        if cancel is not None and cancel.is_set():return False
        written=stream.write(pending)
        if not written:raise BrokenPipeError('Archive input pipe closed')
        pending=pending[written:]
    return True


def create_archive_response(cam_info, records, start, end, as_attachment=False, audio=False):
    """Stream sequential recorder files through one bounded remux pipeline.

    DownloadStart asks the recorder for its fastest file transfer (no realtime
    throttling). FFmpeg stream-copies video; 1-second fragments flush media before
    a long camera GOP completes. More CPU cannot accelerate physical HDD/network.
    """
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:return jsonify(error='FFmpeg не установлен'),503
    service=current_app.extensions['vwshub_media'];limits=resources()
    plain_camera=dict(cam_info);plain_camera['password']=dec_pwd(cam_info.get('password',''))
    play_id=request.args.get('play_id','')
    owner=session.get('archive_consumer')
    operation_key=(owner,play_id) if owner and re.fullmatch(r'[A-Za-z0-9_-]{8,100}',play_id) else None
    with service.lock:
        if operation_key and operation_key in service.cancelled:return jsonify(error='Запрос архива отменён'),409
    if not service.reserve(limits['max_archive_streams']):return jsonify(error='Достигнут лимит архивных сеансов сервера'),429
    idle=max(30,min(600,limits['archive_idle_seconds']))
    chunks=queue.Queue(maxsize=max(8,min(4096,int(limits['archive_buffer_mb'])*32)))
    cancelled=threading.Event();lock=threading.Lock()
    state={'cam':None,'proc':None,'worker':None,'cleaned':False,'error':None,'metadata':{},'frames':0,'bytes_out':0}
    began=time.monotonic()
    hardware_event(service.runtime,'archive.open',cam_info,start=start,end=end,files=len(records),audio=audio,download=as_attachment)
    def close_cam():
        with lock:cam=state.pop('cam',None)
        if cam is not None:
            sock=getattr(cam,'socket',None)
            try:cam.socket.shutdown(socket.SHUT_RDWR)
            except Exception:pass
            try:cam.close()
            except Exception:pass
            if sock is not None:
                try:sock.close()
                except Exception:pass
    def cleanup():
        with lock:
            if state['cleaned']:return
            state['cleaned']=True
        cancelled.set();close_cam()
        proc=state.get('proc')
        if proc and proc.poll() is None:
            try:proc.terminate();proc.wait(timeout=2)
            except Exception:
                try:proc.kill()
                except Exception:pass
        worker=state.get('worker')
        if worker and worker is not threading.current_thread():worker.join(timeout=2)
        if operation_key:
            with service.lock:
                if service.operations.get(operation_key,{}).get('cancel') is cleanup:service.operations.pop(operation_key,None)
        service.release()
    def put(value):
        blocked_since=time.monotonic()
        while not cancelled.is_set():
            try:chunks.put(value,timeout=.25);return True
            except queue.Full:
                # A paused/slow client keeps a bounded queue, not an ever-growing
                # buffer. Stop only after the configured interval with no room
                # for another chunk; ordinary short buffering must drain fully.
                if time.monotonic()-blocked_since>idle:
                    cleanup();return False
        return False
    # Decode credentials once inside the request context, never in background
    # Flask-less threads. This copy is local and never logged or returned.
    def connect_worker():
        def register(cam):
            with lock:
                if cancelled.is_set():return False
                state['cam']=cam
            return True
        cam=open_dvr_connection(plain_camera,plain_camera['password'],register)
        cam.timeout=10
        cam.archive_idle_timeouts=math.ceil(idle/10)
        try:cam.socket.settimeout(min(10,idle/3))
        except Exception:pass
        with lock:
            if cancelled.is_set():cam.close();return None
            state['cam']=cam
        return cam
    def source():
        for record in records:
            if cancelled.is_set():return
            cam=connect_worker()
            if cam is None:return
            try:
                left=max(start,record['BeginTime']);right=min(end,record['EndTime'])
                yield from dvrip_playback_chunks(cam,record['FilePath'],left,right,mode='files',channel=int(cam_info.get('channel',0)),cancel=cancelled)
            finally:close_cam()
    def worker():
        proc=None;frames=None;reader=None
        try:
            metadata=state['metadata']
            frames=iter_dvr_audio_frames(source(),metadata) if audio else iter_dvr_video_frames(source(),metadata)
            first=next(frames,None)
            if first is not None:state['frames']=1
            if first is None:raise RuntimeError('В записи нет поддерживаемого звука' if audio else 'Регистратор не передал видеокадры')
            fmt,data=first
            cmd=[ffmpeg,'-hide_banner','-loglevel','error','-fflags','+genpts+discardcorrupt','-err_detect','ignore_err','-probesize','32768','-analyzeduration','0','-f',fmt]
            if audio:cmd+=['-ar','8000','-ac','1']
            elif 1<=metadata.get('fps',0)<=120:
                # h264/hevc/m4v share FFmpeg's raw demuxer, whose default is
                # 25fps. Wrapper FPS supplies its fallback when SPS/VUI timing
                # is absent; do not force an output rate or duplicate frames.
                cmd+=['-framerate',str(metadata['fps'])]
            cmd+=['-i','pipe:0']
            # ByName firmware may start at the file's first keyframe even when
            # StartTime was supplied. Trim generated media timestamps only when
            # the recorder's wrapper confirms an earlier actual start.
            actual=metadata.get('start_time')
            if actual:
                offset=(datetime.strptime(start,'%Y-%m-%d %H:%M:%S')-datetime.strptime(actual,'%Y-%m-%d %H:%M:%S')).total_seconds()
                if offset>1:cmd+=['-ss',str(offset)]
            if as_attachment:cmd+=['-t',str((datetime.strptime(end,'%Y-%m-%d %H:%M:%S')-datetime.strptime(start,'%Y-%m-%d %H:%M:%S')).total_seconds())]
            if audio:cmd+=['-vn','-c:a','aac','-b:a','64k','-f','adts','pipe:1']
            else:cmd+=['-map','0:v:0','-c:v','copy','-an','-movflags','frag_keyframe+empty_moov+default_base_moof','-frag_duration','1000000','-flush_packets','1','-f','mp4','pipe:1']
            proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
            with lock:state['proc']=proc
            if cancelled.is_set():return
            def errors():
                try:
                    for line in iter(proc.stderr.readline,b''):
                        if line:log.debug('Archive remux: %s',line.decode(errors='replace').strip()[:350])
                except Exception:pass
            def output():
                try:
                    while not cancelled.is_set():
                        part=proc.stdout.read(32768)
                        if not part or not put(part):break
                        state['bytes_out']+=len(part)
                except Exception:pass
            threading.Thread(target=errors,daemon=True,name='archive-stderr').start()
            reader=threading.Thread(target=output,daemon=True,name='archive-output');reader.start()
            if not _write_all(proc.stdin,data,cancelled):return
            for _,data in frames:
                state['frames']+=1
                if cancelled.is_set() or proc.poll() is not None:break
                if not _write_all(proc.stdin,data,cancelled):break
            try:proc.stdin.close()
            except Exception:pass
            # stdout can legitimately block on browser/network backpressure.
            # Keep the last fragments until fully drained or explicitly stopped;
            # fixed 20s/3s deadlines truncated slow downloads after stdin EOF.
            while not cancelled.is_set():
                try:proc.wait(timeout=.25);break
                except subprocess.TimeoutExpired:continue
            while reader and reader.is_alive() and not cancelled.is_set():
                reader.join(timeout=.25)
        except Exception as exc:
            if not cancelled.is_set():
                hardware_event(service.runtime,'archive.failed',cam_info,level='error',error_type=type(exc).__name__)
                state['error']='Не удалось прочитать архив. Проверьте регистратор, канал и доступность записи.'
                log.warning('Archive transfer failed for device %s: %s',cam_info.get('id'),type(exc).__name__)
        finally:
            if frames:
                try:frames.close()
                except Exception:pass
            close_cam()
            if proc:
                if proc.poll() is None:
                    try:proc.terminate()
                    except Exception:pass
                for stream in (proc.stdin,proc.stdout,proc.stderr):
                    try:stream.close()
                    except Exception:pass
            hardware_event(service.runtime,'archive.closed',cam_info,frames=state['frames'],bytes_out=state['bytes_out'],
                           fps=state['metadata'].get('fps'),actual_start=state['metadata'].get('start_time'),audio=audio,cancelled=cancelled.is_set(),
                           ffmpeg_returncode=proc.poll() if proc else None,duration_ms=round((time.monotonic()-began)*1000))
            put(None)
    if operation_key:
        with service.lock:
            if operation_key in service.cancelled or operation_key in service.operations:
                cleanup();return jsonify(error='Запрос архива отменён или уже запущен'),409
            service.operations[operation_key]={'camera':str(cam_info['id']),'cancel':cleanup}
    worker_thread=threading.Thread(target=worker,daemon=True,name='archive-transfer');state['worker']=worker_thread;worker_thread.start()
    try:first=chunks.get(timeout=min(90,idle))
    except queue.Empty:cleanup();return jsonify(error='Регистратор долго не отвечает. Повторите запрос или уменьшите период.'),504
    if first is None:
        message=state['error'] or 'В записи нет поддерживаемого медиа';cleanup();return jsonify(error=message),502
    def generate():
        try:
            yield first
            last=time.monotonic()
            while not cancelled.is_set():
                try:part=chunks.get(timeout=1)
                except queue.Empty:
                    if not worker_thread.is_alive() or time.monotonic()-last>idle:break
                    continue
                if part is None:break
                last=time.monotonic();yield part
        finally:cleanup()
    headers={'Cache-Control':'no-store','X-Accel-Buffering':'no','Accept-Ranges':'none','X-VWSHub-Archive-Camera':str(cam_info['id']),'X-VWSHub-Archive-Channel':str(cam_info.get('channel',0))}
    if state['metadata'].get('fps'):headers['X-VWSHub-Archive-Frame-Rate']=str(state['metadata']['fps'])
    if state['metadata'].get('start_time'):headers['X-VWSHub-Archive-Actual-Start']=state['metadata']['start_time']
    if as_attachment:
        name=secure_filename(str(cam_info.get('name') or cam_info['id'])) or 'camera'
        stamp=lambda t:datetime.strptime(t,'%Y-%m-%d %H:%M:%S').strftime('%Y%m%d_%H%M%S')
        headers['Content-Disposition']=f'attachment; filename="{name}_{stamp(start)}-{stamp(end)}.mp4"'
    response=Response(stream_with_context(generate()),mimetype='audio/aac' if audio else 'video/mp4',headers=headers)
    response.call_on_close(cleanup)
    return response


def register_media(app, rt):
    service=MediaService(app,rt);app.extensions['vwshub_media']=service
    bp=Blueprint('media',__name__)
    def authorized(cam_id,archive=False):
        user=rt.current_user()
        if not user:return None,(jsonify(error='Требуется авторизация'),401)
        cam=rt.get_camera(str(cam_id or ''))
        if not cam:return None,(jsonify(error='Камера не найдена'),404)
        if not rt.can_access_camera(user,str(cam['id'])):return None,(jsonify(error='Камера не предоставлена пользователю'),403)
        if archive and not rt.can_access_archive(user):return None,(jsonify(error='Доступ к архиву запрещён'),403)
        if archive and cam.get('protocol','dvrip')!='dvrip':return None,(jsonify(error='Архив XMEye доступен для DVRIP-каналов'),400)
        if archive and not session.get('archive_consumer'):session['archive_consumer']=uuid.uuid4().hex
        return cam,None
    def range_args():
        start=normalize_time(request.args.get('start'));end=normalize_time(request.args.get('end'))
        if start>=end:raise ValueError('Начало периода должно быть раньше конца')
        return start,end
    def live_consumer(value=None):
        if value is not None:
            if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{32}',value):raise ValueError('Неверный идентификатор видеостены')
            return rt.current_user()['username']+':'+value
        if 'live_consumer' not in session:session['live_consumer']=uuid.uuid4().hex
        return session['live_consumer']
    @bp.post('/api/live/stop')
    def stop_live():
        body=request.get_json(silent=True) or {};cam,err=authorized(body.get('cam_id'))
        if err:return err
        service.live.release(cam['id'],body.get('stream','main'),live_consumer(body.get('consumer')))
        return jsonify(success=True)
    @bp.get('/live/<cam_id>/<stream>/index.m3u8')
    def live_playlist(cam_id,stream):
        cam,err=authorized(cam_id)
        if err:return err
        consumer=request.args.get('consumer');lease=live_consumer(consumer)
        try:
            began=time.monotonic()
            item=service.live.ensure(cam_id,stream,lease);playlist=item['directory']/'index.m3u8'
            deadline=time.monotonic()+12
            while not playlist.exists() and time.monotonic()<deadline and item['process'].poll() is None:time.sleep(.1)
            if not playlist.exists():
                if not item.get('reported_failure'):
                    item['reported_failure']=True;hardware_event(rt,'live.failed',cam,level='error',stream=stream,ffmpeg_returncode=item['process'].poll(),duration_ms=round((time.monotonic()-began)*1000))
                return jsonify(error='Поток ещё не готов или недоступен'),503
            if not item.get('reported_ready'):
                item['reported_ready']=True;hardware_event(rt,'live.ready',cam,stream=stream,duration_ms=round((time.monotonic()-began)*1000))
            if consumer:
                lines=[line+'?consumer='+consumer if re.fullmatch(r'seg_\d+\.ts',line) else line for line in playlist.read_text(encoding='utf-8').splitlines()]
                return Response('\n'.join(lines)+'\n',mimetype='application/vnd.apple.mpegurl',headers={'Cache-Control':'no-store'})
            return send_from_directory(item['directory'],'index.m3u8',mimetype='application/vnd.apple.mpegurl',max_age=0)
        except (ValueError,RuntimeError) as exc:return jsonify(error=str(exc)),503
    @bp.get('/live/<cam_id>/<stream>/<path:filename>')
    def live_segment(cam_id,stream,filename):
        cam,err=authorized(cam_id)
        if err:return err
        if stream not in ('main','sub') or not re.fullmatch(r'seg_\d+\.ts',filename):return jsonify(error='Сегмент не найден'),404
        with service.live.lock:
            item=service.live.streams.get((cam_id,stream))
            if not item:return jsonify(error='Поток не запущен'),404
            item.setdefault('leases',{})[live_consumer(request.args.get('consumer'))]=time.monotonic()
            directory=item['directory']
        return send_from_directory(directory,filename,mimetype='video/mp2t',max_age=0)
    @bp.get('/api/recordings')
    def recordings():
        cam,err=authorized(request.args.get('cam_id'),True)
        if err:return err
        try:
            start,end=range_args();mode=request.args.get('mode','files')
            if mode not in ('files','time'):raise ValueError('Неизвестный режим архива')
            records=service.query_files(cam,start,end)
            return jsonify(records if mode=='files' else _group_recordings(records))
        except (ValueError,TypeError,AttributeError) as exc:return jsonify(error=str(exc)),400
        except Exception:return jsonify(error='Не удалось получить записи выбранного канала'),502
    def archive_response(attachment=False,audio=False):
        cam,err=authorized(request.args.get('cam_id'),True)
        if err:return err
        try:
            start,end=range_args();path=(request.args.get('path') or '').strip()
            if len(path)>2048 or '\x00' in path:raise ValueError('Некорректный путь записи')
            if request.args.get('mode','files') not in ('files','time'):raise ValueError('Неизвестный режим архива')
            if audio and not service.audio_capabilities(cam,refresh=True)['supported']:return jsonify(error='Устройство не подтвердило поддерживаемый включённый микрофон'),409
            records=service.resolve(cam,start,end,path)
            # A single playback file is never replaced by a ByTime/channel-0 request.
            if not attachment and not path:raise ValueError('Для просмотра выберите точный файл архива')
            rt.audit('archive.download' if attachment else 'archive.audio' if audio else 'archive.playback',{'device_id':cam['id'],'start':start,'end':end,'files':len(records)})
            return create_archive_response(cam,records,start,end,attachment,audio)
        except (ValueError,TypeError,AttributeError) as exc:return jsonify(error=str(exc)),400
        except Exception:return jsonify(error='Не удалось открыть архив выбранного канала'),502
    @bp.get('/api/playback')
    def playback():return archive_response()
    @bp.get('/api/download')
    def download():return archive_response(True)
    @bp.get('/api/archive/audio')
    def archive_audio():return archive_response(audio=True)
    @bp.post('/api/archive/stop')
    def stop_archive():
        value=request.get_json(silent=True) or {};cam,err=authorized(value.get('cam_id'),True)
        if err:return err
        play_id=value.get('play_id','')
        if not isinstance(play_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',play_id):return jsonify(error='Некорректный идентификатор архивного сеанса'),400
        service.cancel_operation(session.get('archive_consumer'),play_id,cam['id'])
        return jsonify(success=True)
    @bp.get('/api/archive/capabilities')
    def archive_capabilities():
        cam,err=authorized(request.args.get('cam_id'),True)
        if err:return err
        try:return jsonify(audio=service.audio_capabilities(cam,refresh=request.args.get('refresh')=='1'),streaming={'download_mode':'ByName','buffer_mb':resources()['archive_buffer_mb'],'idle_seconds':resources()['archive_idle_seconds'],'fragment_seconds':1})
        except Exception:return jsonify(audio={'enabled':False,'supported':False,'reason':'Не удалось прочитать состояние микрофона'})
    @bp.get('/api/cameras/<cam_id>/snapshot')
    def camera_snapshot(cam_id):
        cam,err=authorized(cam_id)
        if err:return err
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:return jsonify(error='FFmpeg не установлен'),503
        fmt=request.args.get('format',rt.settings().get('snapshot_format','jpeg')).lower()
        codecs={'jpeg':('mjpeg','image/jpeg','jpg'),'png':('png','image/png','png'),'webp':('libwebp','image/webp','webp')}
        if fmt not in codecs:return jsonify(error='Формат снимка: jpeg, png или webp'),400
        codec,mime,extension=codecs[fmt]
        try:
            result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-rtsp_transport','tcp','-i',build_rtsp_live_url(cam,'main'),'-frames:v','1','-an','-c:v',codec,'-f','image2pipe','pipe:1'],capture_output=True,timeout=15)
            if result.returncode or not result.stdout:return jsonify(error='Не удалось получить снимок камеры'),502
            return Response(result.stdout,mimetype=mime,headers={'Cache-Control':'no-store','Content-Disposition':f'attachment; filename="camera_{cam_id}_{int(time.time())}.{extension}"'})
        except subprocess.TimeoutExpired:return jsonify(error='Камера не ответила на запрос снимка'),504
    @bp.post('/api/cameras/test')
    def test_camera():
        me=rt.current_user()
        if not me or me.get('role')!='admin':return jsonify(error='Требуются права администратора'),403
        body=request.get_json(silent=True) or {}
        existing=rt.get_camera(str(body.get('id',''))) or {}
        draft={**existing,**{k:v for k,v in body.items() if k in {'ip','protocol','username','port','rtsp_port','rtsp_host','rtsp_path','rtsp_sub_path','channel'}}}
        password=body.get('password')
        draft['password']=rt.enc_pwd(password) if password else existing.get('password','')
        try:
            if not isinstance(draft.get('ip'),str) or not draft['ip'].strip() or re.search(r'[\s/@?#\\]',draft['ip']):raise ValueError('Укажите IP-адрес или имя узла')
            if draft.get('rtsp_host') and (not isinstance(draft['rtsp_host'],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+',draft['rtsp_host']) or '..' in draft['rtsp_host']):raise ValueError('Некорректный узел RTSP')
            if draft.get('protocol') not in ('dvrip','onvif'):raise ValueError('Укажите протокол устройства')
            for key,default in [('port',34567 if draft['protocol']=='dvrip' else 80),('rtsp_port',554)]:
                draft[key]=int(draft.get(key) or default)
                if not 1<=draft[key]<=65535:raise ValueError('Порт должен быть от 1 до 65535')
            if draft['protocol']=='dvrip':
                connection=dvr_connect(draft)
                try:return jsonify(ok=True,message='Регистратор подтвердил авторизацию')
                finally:connection.close()
            ffmpeg=shutil.which('ffmpeg')
            if not ffmpeg:return jsonify(ok=False,error='FFmpeg не установлен'),503
            result=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-rtsp_transport','tcp','-i',build_rtsp_live_url(draft),'-frames:v','1','-an','-f','null','-'],capture_output=True,timeout=15)
            return jsonify(ok=result.returncode==0,**({'error':'Камера не передала видеокадр'} if result.returncode else {'message':'Видеопоток получен'}))
        except ValueError as exc:return jsonify(error=str(exc)),400
        except subprocess.TimeoutExpired:return jsonify(ok=False,error='Устройство не ответило за отведённое время'),504
        except Exception:return jsonify(ok=False,error='Проверьте адрес, протокол и учётные данные устройства'),502
    app.register_blueprint(bp)
    return service

