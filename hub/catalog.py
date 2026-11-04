"""Recorder identities, scoped editing, portable catalogs and administration."""
from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import Blueprint, abort, g, jsonify, request, send_file, session

from .backup import MAX_BYTES, validate_backup
from .core import admin_required, body, connection_signature, ids, integer, public_device, text, validate_device
from .store import DataStore, protected


def recorder_channels(runtime, camera):
    if camera.get("protocol") == "onvif": return onvif_channels(runtime,camera)
    from .media import open_dvr_connection

    started = time.monotonic()
    connection = None
    try:
        connection = open_dvr_connection(camera, runtime.dec_pwd(camera.get("password", "")))
        info = connection.get_system_info()
        if not isinstance(info, dict): raise ValueError("Регистратор не предоставил сведения о каналах")
        info = info.get("SystemInfo", info)
        try: titles = connection.get_channel_titles()
        except Exception as exc:
            titles = []
            runtime.hardware.record("recorder.titles_unavailable",camera,level="warning",error_type=type(exc).__name__)
        if isinstance(titles, dict): titles = titles.get("ChannelTitle", [])
        if not isinstance(titles, list): titles = []
        counts = [len(titles)]
        for key in ("VideoInChannel", "ChannelNum", "VideoChannel", "DigitalVideoInChannel", "DigChannel"):
            value = info.get(key)
            if isinstance(value, int) and not isinstance(value, bool): counts.append(value)
            elif isinstance(value, str) and value.isdigit(): counts.append(int(value))
        count = max(counts)
        runtime.hardware.record("recorder.channel_capabilities",camera,reported_counts={key:info[key] for key in ("VideoInChannel","ChannelNum","VideoChannel","DigitalVideoInChannel","DigChannel") if key in info},titles_received=len(titles))
        if count < 1:
            encoded = connection.get_encode_info()
            if isinstance(encoded, dict): encoded = encoded.get("Simplify.Encode", [])
            if isinstance(encoded, list): count = len(encoded)
        count = integer(count, "Число каналов, сообщённое регистратором", 1, 256)
        channels = []
        for channel in range(count):
            label = titles[channel] if channel < len(titles) and isinstance(titles[channel], str) else ""
            label = " ".join(label.split())[:100] or "Канал " + str(channel + 1)
            channels.append({"channel": channel, "name": label})
        runtime.hardware.record("recorder.channels", camera, duration_ms=round((time.monotonic() - started) * 1000), channel_count=count,
                                model=info.get("DeviceType"), firmware=info.get("SoftWareVersion"))
        return channels
    except Exception as exc:
        runtime.hardware.record("recorder.channels_failed", camera, level="error", error_type=type(exc).__name__, duration_ms=round((time.monotonic() - started) * 1000))
        raise
    finally:
        if connection is not None: connection.close()


def onvif_channels(runtime,camera):
    from .devices import connect_onvif,plain
    began=time.monotonic()
    try:
        client=connect_onvif(runtime,camera);service=client.create_media_service()
        profiles=plain(service.GetProfiles());sources={}
        if not isinstance(profiles,list):raise ValueError("ONVIF не предоставил профили каналов")
        for profile in profiles:
            if not isinstance(profile,dict):continue
            source=(profile.get("VideoSourceConfiguration") or {}).get("SourceToken")
            token=profile.get("token")
            if not isinstance(source,str) or not source or not isinstance(token,str) or not token:continue
            sources.setdefault(source,[]).append(profile)
        if not sources or len(sources)>256:raise ValueError("Не удалось определить источники видео ONVIF")
        def quality(profile):
            encoder=profile.get("VideoEncoderConfiguration") or {};resolution=encoder.get("Resolution") or {}
            return (encoder.get("Encoding")=="H264",int(resolution.get("Width") or 0)*int(resolution.get("Height") or 0))
        channels=[]
        for index,(source_token,profiles) in enumerate(sources.items()):
            profiles=sorted(profiles,key=quality,reverse=True);main=profiles[0]
            sub=min((p for p in profiles if quality(p)[0]),key=quality,default=profiles[-1])
            def uri(profile):
                response=plain(service.GetStreamUri({"StreamSetup":{"Stream":"RTP-Unicast","Transport":{"Protocol":"RTSP"}},"ProfileToken":profile["token"]}))
                address=urlsplit(response.get("Uri","") if isinstance(response,dict) else "")
                if address.scheme!="rtsp" or not address.hostname:raise ValueError("ONVIF не предоставил RTSP-адрес профиля")
                return (address.path or "/")+("?"+address.query if address.query else ""),address.port or int(camera.get("rtsp_port",554)),address.hostname
            main_path,port,host=uri(main);sub_path,sub_port,sub_host=uri(sub)
            if sub_port!=port or sub_host!=host:sub_path=main_path
            channels.append({"channel":index,"name":text(main.get("Name") or "Канал "+str(index+1),"Канал ONVIF",150,True),
                             "source_token":source_token,"profile_token":text(main["token"],"Профиль ONVIF",256,True),"rtsp_path":main_path,"rtsp_sub_path":sub_path,"rtsp_port":port,"rtsp_host":host})
        runtime.hardware.record("recorder.channels",camera,channel_count=len(channels),duration_ms=round((time.monotonic()-began)*1000))
        return channels
    except Exception as exc:
        runtime.hardware.record("recorder.channels_failed",camera,level="error",error_type=type(exc).__name__)
        raise


def check_status(runtime, app, devices):
    """Probe physical services once, rather than flooding a DVR once per channel."""
    physical = {}
    for camera in devices: physical.setdefault(DataStore.connection_key(camera), []).append(camera)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    media = app.extensions.get("vwshub_media")
    healthy, healthy_sources = set(), set()
    if media:
        with media.live.lock:
            for (cam_id, stream_kind), item in list(media.live.streams.items()):
                if str(stream_kind).startswith("audio-"):continue
                manifest = item["directory"] / "index.m3u8"
                try:
                    if item["process"].poll() is None and time.time() - manifest.stat().st_mtime < 20 and "#EXTINF:" in manifest.read_text(encoding="utf-8"):
                        camera = runtime.get_camera(cam_id)
                        if camera:
                            healthy.add(DataStore.connection_key(camera));healthy_sources.add(str(camera["id"]))
                except OSError: pass

    def evidence(camera, reachable, method, port=None):
        key=DataStore.connection_key(camera)
        observations=getattr(runtime,"device_health",{}).get(key,{})
        def fresh(checked,ttl):
            return isinstance(checked,(int,float)) and not isinstance(checked,bool) and checked>0 and 0<=time.monotonic()-checked<ttl
        recent=fresh(observations.get("management_checked"),120)
        services={
            "network":{"state":"reachable" if reachable else "unreachable","evidence":method},
            "management":{"state":"confirmed" if recent and reachable else "unverified" if reachable else "unreachable", "evidence":"authenticated_operation" if recent and reachable else "not_authenticated"},
            "live":{"state":"confirmed" if str(camera["id"]) in healthy_sources else "unverified","evidence":"recent_hls_segments" if str(camera["id"]) in healthy_sources else "not_playing"},
            "archive":{"state":"confirmed" if reachable and fresh(observations.get("archive_sources",{}).get(str(camera["id"])),300) else "unverified","evidence":"delivered_media" if reachable and fresh(observations.get("archive_sources",{}).get(str(camera["id"])),300) else "not_tested"},
            "audio":{"state":"unverified","live_audio":"unverified","archive_audio":"unverified","evidence":"not_tested"},
        }
        profiles={}
        for stream in ("main","sub"):
            probe=observations.get("live_audio_sources",{}).get(str(camera["id"])+"|"+stream,{})
            profiles[stream]="supported" if probe.get("supported") is True else "unsupported" if probe.get("supported") is False else "unverified"
            if not fresh(probe.get("checked"),300):profiles[stream]="unverified"
        audio_state="supported" if "supported" in profiles.values() else "unsupported" if all(v=="unsupported" for v in profiles.values()) else "unverified"
        services["audio"].update(state=audio_state,live_audio=audio_state,profiles=profiles,evidence="live_profile_probes" if any(v!="unverified" for v in profiles.values()) else "not_tested")
        if port is not None:services["network"]["port"]=port
        return services

    def probe(item):
        key, members = item
        camera = members[0]
        if key in healthy:
            return members, {"online": True, "overall":"partial", "services":evidence(camera,True,"live"),
                             "checked_at": stamp, "method": "live", "reason": "Видео получено; остальные службы проверяются независимо"}
        candidates = list(dict.fromkeys([int(camera.get("port", 34567 if camera.get("protocol") == "dvrip" else 80)),
                                        *[int(member.get("rtsp_port", 554)) for member in members]]))
        failures = []
        began = time.monotonic()
        for port in candidates:
            for attempt in range(2 if port == candidates[0] else 1):
                try:
                    with socket.create_connection((camera["ip"], port), timeout=1.5 + attempt * .5): pass
                    runtime.hardware.record("status.online", camera, port_checked=port, duration_ms=round((time.monotonic() - began) * 1000), channels=len(members),stage="network",result="port_open")
                    method="tcp" if port==candidates[0] else "rtsp"
                    return members, {"online": True, "overall":"partial", "services":evidence(camera,True,method,port), "checked_at": stamp, "port": port, "method": method,
                                     "reason": "Сетевой порт отвечает; авторизация управления и медиа ещё не подтверждены" if port == candidates[0] else "RTSP-порт отвечает; управление не подтверждено"}
                except OSError as exc: failures.append(type(exc).__name__)
        runtime.hardware.record("status.unreachable", camera, level="warning", ports_checked=candidates, errors=failures,
                                duration_ms=round((time.monotonic() - began) * 1000), channels=len(members),stage="network")
        return members, {"online": False,"overall":"offline", "services":evidence(camera,False,"tcp"), "checked_at": stamp, "method": "tcp", "checked_ports": candidates,
                         "reason": "Службы устройства не ответили. Причиной могут быть питание, сеть, маршрутизация или firewall; ICMP проверяется отдельно."}

    result = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(physical)))) as pool:
        for members, status in pool.map(probe, physical.items()):
            for camera in members:
                services=evidence(camera,status["online"],status["method"],status.get("port"))
                confirmed=all(services[k]["state"]=="confirmed" for k in ("management","live","archive"))
                overall="online" if status["online"] and confirmed else "partial" if status["online"] else "offline"
                result[camera["id"]] = {**status,"overall":overall,"services":services}
    return result, stamp


def register_catalog(app, runtime):
    bp = Blueprint("catalog", __name__)

    def draft(data):
        source = None
        if data.get("recorder_id"):
            source = next((c for c in runtime.store.get_devices() if c.get("recorder_id") == data["recorder_id"]), None)
        data = {**data, "name": data.get("name") or "Видеорегистратор"}
        return validate_device(data, source, runtime)

    @bp.get("/api/recorders")
    def recorders():
        visible = runtime.visible_devices()
        result = []
        for recorder in runtime.store.get_recorders():
            members = [c for c in visible if c.get("recorder_id") == recorder["id"]]
            if not members: continue
            protocol, host, port = recorder["connection_key"].split("|", 2)
            result.append({"id": recorder["id"], "name": recorder["name"], "protocol": protocol, "ip": host, "port": int(port),
                           "camera_ids": [c["id"] for c in members], "camera_count": len(members), "cam_id": members[0]["id"] if members else None})
        return jsonify(result)

    @bp.patch("/api/recorders/<recorder_id>")
    @admin_required
    def rename_recorder(recorder_id):
        data = body()
        if set(data) != {"name"}: raise ValueError("Здесь меняется только имя устройства на сайте")
        with runtime.store.lock:
            values = runtime.store.get_recorders()
            target = next((r for r in values if r["id"] == recorder_id), None)
            if target is None: abort(404)
            target["name"] = text(data["name"], "Имя устройства", 150, True)
            runtime.store.save_recorders(values)
        runtime.audit("recorder.renamed", {"id": recorder_id})
        return jsonify(success=True, recorder=target)

    @bp.post("/api/recorders/probe")
    @admin_required
    def probe_recorder():
        camera = draft(body())
        try: return jsonify(success=True, channels=recorder_channels(runtime, camera))
        except Exception: return jsonify(error="Не удалось прочитать каналы. Проверьте адрес, порт протокола и права учётной записи; подробности в диагностике оборудования."), 502

    @bp.post("/api/recorders")
    @admin_required
    def add_recorder():
        return jsonify(error="Добавление всех каналов без выбора отключено. Получите список через /api/inventory/probe и сохраните выбранные каналы через /api/inventory."),410

    @bp.patch("/api/cameras/<cam_id>")
    def rename_camera(cam_id):
        data = body(); me = runtime.current_user()
        if set(data) != {"name"}: raise ValueError("Редактору доступно только название камеры")
        with runtime.store.lock:
            if not runtime.can_edit_camera(me, cam_id): abort(403)
            values = runtime.store.get_devices(); camera = next((c for c in values if c["id"] == cam_id), None)
            if camera is None: abort(404)
            camera["name"] = text(data["name"], "Название камеры", 150, True); runtime.store.save_devices(values)
        runtime.audit("camera.renamed", {"id": cam_id})
        return jsonify(success=True, camera=public_device(camera,connection=me["role"]=="admin"))

    @bp.delete("/api/groups/<group_id>/cameras/<cam_id>")
    def detach_camera(group_id, cam_id):
        with runtime.store.lock:
            if not runtime.can_edit_group(runtime.current_user(), group_id): abort(403)
            values = runtime.store.get_groups(); group = next((g for g in values if g["id"] == group_id), None)
            if group is None or cam_id not in group.get("camera_ids", []): abort(404)
            group["camera_ids"].remove(cam_id); runtime.store.save_groups(values)
        runtime.audit("group.camera_detached", {"group_id": group_id, "camera_id": cam_id})
        return jsonify(success=True)

    @bp.get("/api/cameras/export")
    @admin_required
    def export_cameras():
        include = request.args.get("include_passwords") == "1"
        if include:raise ValueError("Для переноса учётных данных используйте защищённый экспорт в разделе «Устройства»")
        from .transfers import safe_path
        cameras = []
        for camera in runtime.store.get_devices():
            item = public_device(camera)
            for key in ("rtsp_path","rtsp_sub_path"):
                if key in item:item[key]=safe_path(item[key])
            item["group_ids"] = [g["id"] for g in runtime.store.get_groups() if camera["id"] in g.get("camera_ids", [])]
            if include: item["password"] = runtime.dec_pwd(camera.get("password", ""))
            cameras.append(item)
        result = {"format": "vwshub.cameras", "version": 1, "includes_passwords": include, "cameras": cameras,
                  "groups": [{"id": g["id"], "name": g["name"]} for g in runtime.store.get_groups()],
                  "recorders": [{k:r[k] for k in ("id","name","connection_key") if k in r} for r in runtime.store.get_recorders()]}
        runtime.audit("cameras.exported", {"count": len(cameras), "with_secrets": include})
        return send_file(io.BytesIO(json.dumps(result, ensure_ascii=False, indent=2).encode()), mimetype="application/json", as_attachment=True, download_name="vwshub-cameras.json")

    @bp.post("/api/cameras/import")
    @admin_required
    def import_cameras():
        return jsonify(error="Прямой импорт отключён. Используйте /api/transfers/devices/preview и /api/transfers/devices/apply."),410

    @bp.get("/api/hardware/logs")
    @admin_required
    def hardware_logs():
        return jsonify(logs=runtime.hardware.entries(integer(request.args.get("limit", 300), "Лимит", 1, 1000)))

    @bp.get("/api/hardware/logs/export")
    @admin_required
    def export_hardware_logs():
        lines = [json.dumps(entry, ensure_ascii=False) for entry in reversed(runtime.hardware.entries(100000))]
        return send_file(io.BytesIO(("\n".join(lines) + "\n").encode()), mimetype="application/x-ndjson", as_attachment=True,
                         download_name="vwshub-hardware-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".jsonl")

    @bp.post("/api/logs/clear")
    @admin_required
    def clear_logs():
        data = body(); kind = data.get("kind", "audit")
        if data.get("confirm") is not True or not isinstance(kind, str) or kind not in {"audit", "hardware"}: raise ValueError("Подтвердите очистку выбранного журнала")
        if kind == "hardware": runtime.hardware.clear()
        else:
            with runtime.store.lock:
                path = runtime.store.audit_file
                for file in [path] + [path.with_name(path.name + f".{i}") for i in (1, 2, 3)]:
                    if file.exists(): file.unlink()
        runtime.audit("logs.cleared", {"kind": kind})
        return jsonify(success=True)

    def uploaded_backup():
        source = request.files.get("file")
        if source is None: raise ValueError("Выберите ZIP backup")
        raw = source.stream.read(MAX_BYTES + 1)
        files, summary = validate_backup(raw)
        return files, summary

    @bp.post("/api/backup/inspect")
    @admin_required
    def inspect_backup():
        _, summary = uploaded_backup()
        return jsonify(success=True, backup=summary)

    @bp.post("/api/backup/restore")
    @admin_required
    def restore_backup():
        if request.form.get("confirmation") != "RESTORE": raise ValueError("Введите RESTORE для подтверждения замены данных")
        files, summary = uploaded_backup()
        if request.form.get("sha256") != summary["sha256"]: raise ValueError("Backup изменился после проверки. Проверьте файл повторно")
        actor = runtime.current_user()["username"]
        next_secret=os.getenv("FLASK_SECRET_KEY") or files[".flask_secret"].decode("utf-8").strip()
        runtime.maintenance = True
        try:
            media = app.extensions.get("vwshub_media")
            if media:
                media.live.stop_all()
                with media.lock: operations = list(media.operations.values())
                for operation in operations: operation["cancel"]()
                with media.lock:
                    media.files.clear(); media.audio_cache.clear()
                    getattr(media,"live_audio_cache",{}).clear()
                    getattr(media,"live_probe_cache",{}).clear()
            with runtime.store.lock:
                runtime.store.images.snapshot("restore","restore-backups")
                runtime.store.restore(files)
                app.secret_key = next_secret
                session.clear(); g.vwshub_user = None
        finally:
            runtime.maintenance = False
        runtime.store.audit(actor, "server.backup_restored", {k: summary[k] for k in ("users", "groups", "cameras", "recorders")})
        return jsonify(success=True, login_required=True)

    def status_endpoint():
        data = body(); selected = data.get("camera_ids", data.get("ids"))
        chosen = set(ids(selected)) if selected is not None else None
        devices = [c for c in runtime.visible_devices() if chosen is None or c["id"] in chosen]
        result, stamp = check_status(runtime, app, devices)
        return jsonify(success=True, status=result, checked_at=stamp)

    # Replace the old per-channel TCP probe while preserving its public endpoint.
    app.view_functions["camera_status"] = status_endpoint
    app.register_blueprint(bp)
