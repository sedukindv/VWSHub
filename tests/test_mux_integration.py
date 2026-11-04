"""Real FFmpeg archive remux regressions with synthetic, offline DVRIP input.

Set FFMPEG_BINARY or install ffmpeg in PATH to run these tests. No device is
contacted: only the DVR connection and its NETIP download are replaced. Linux CI
can install ffmpeg with apt; no ffprobe or pytest temporary-directory fixture is
required. Scratch data lives outside the distributable project.
"""
from __future__ import annotations

import os
import json
import re
import shutil
import struct
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, session

from hub import media


WIDTH, HEIGHT, FPS = 320, 240, 15
START = '2026-10-29 12:00:00'
MIDDLE = '2026-10-29 12:00:03'
END = '2026-10-29 12:00:06'


@pytest.fixture(scope='module')
def ffmpeg_binary():
    configured = os.environ.get('FFMPEG_BINARY')
    candidate = shutil.which(configured) if configured else shutil.which('ffmpeg')
    if not candidate:
        pytest.skip('Install ffmpeg in PATH or set FFMPEG_BINARY to its executable')
    return str(Path(candidate).resolve())


@pytest.fixture(scope='module')
def synthetic_clip(ffmpeg_binary):
    folder = Path(__file__).resolve().parents[2] / '.mux-tests' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    clip = folder / 'testsrc-15fps-3s.h264'
    try:
        result = subprocess.run([
            ffmpeg_binary, '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', f'testsrc=size={WIDTH}x{HEIGHT}:rate={FPS}:duration=3',
            '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'ultrafast',
            '-tune', 'zerolatency', '-g', str(FPS), '-keyint_min', str(FPS),
            '-sc_threshold', '0', '-bf', '0', '-f', 'h264', str(clip),
        ], capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        yield folder, clip.read_bytes()
    finally:
        shutil.rmtree(folder)


@pytest.mark.parametrize('codec,container,encoder',[('h264','ts','libx264'),('hevc','fmp4','libx265')])
def test_real_live_copy_preserves_codec_and_decoded_frames(ffmpeg_binary,synthetic_clip,monkeypatch,codec,container,encoder):
    """Real LiveManager command, local input substituted only for synthetic RTSP."""
    ffprobe=shutil.which('ffprobe')
    if not ffprobe:pytest.skip('Install ffprobe for factual codec/container validation')
    folder,_=synthetic_clip
    source=folder/(codec+'-live-source.mp4')
    command=[ffmpeg_binary,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc=size=320x180:rate=10:duration=3',
             '-an','-pix_fmt','yuv420p','-c:v',encoder,'-threads','1','-preset','ultrafast','-g','10','-bf','0']
    if codec=='hevc':command+=['-x265-params','pools=1:frame-threads=1:keyint=10:min-keyint=10:scenecut=0:log-level=error','-tag:v','hvc1']
    command+=[str(source)]
    generated=subprocess.run(command,capture_output=True,timeout=30)
    assert generated.returncode==0,generated.stderr.decode(errors='replace')
    manager=media.LiveManager(folder/('live-'+container))
    original_which=media.shutil.which;original_popen=media.subprocess.Popen
    monkeypatch.setattr(media.shutil,'which',lambda name:ffmpeg_binary if name=='ffmpeg' else original_which(name))
    monkeypatch.setattr(media,'get_camera',lambda camera_id:{'id':camera_id})
    monkeypatch.setattr(media,'resources',lambda:{'max_live_streams':4,'ffmpeg_threads':1})
    monkeypatch.setattr(media,'build_rtsp_live_url',lambda *args:'rtsp://synthetic.invalid/test')
    captured=[]
    def local_transport(command,*args,**kwargs):
        # Keep the production FFmpeg command for assertions; only replace network
        # acquisition with a generated file. No socket or physical device is used.
        if '-rtsp_transport' in command:
            captured.append(list(command));command=list(command)
            position=command.index('-rtsp_transport');del command[position:position+2]
            command[command.index('-i')+1]=str(source)
        return original_popen(command,*args,**kwargs)
    monkeypatch.setattr(media.subprocess,'Popen',local_transport)
    try:
        stream=manager.ensure('synthetic-'+codec,'sub','test:wall',container)
        assert stream['process'].wait(timeout=20)==0,(stream['directory']/'ffmpeg.log').read_text(errors='replace')
        assert captured[0][captured[0].index('-c:v')+1]=='copy'
        assert captured[0][captured[0].index('-rtsp_transport')+1]=='tcp' and '-rw_timeout' not in captured[0]
        playlist=(stream['directory']/'index.m3u8').read_text()
        segments=[line for line in playlist.splitlines() if line and not line.startswith('#')]
        assert segments
        if container=='fmp4':
            assert '#EXT-X-MAP:URI="init.mp4"' in playlist
            assert all(name.endswith('.m4s') for name in segments)
            payload=(stream['directory']/'init.mp4').read_bytes()
        else:
            assert '#EXT-X-MAP' not in playlist and all(name.endswith('.ts') for name in segments)
            payload=b''
        payload+=b''.join((stream['directory']/name).read_bytes() for name in segments)
        output=folder/('live-result-'+codec+('.mp4' if container=='fmp4' else '.ts'))
        output.write_bytes(payload)
        probe=subprocess.run([ffprobe,'-v','error','-count_frames','-show_entries','stream=codec_name,codec_tag_string,width,height,nb_read_frames,extradata',
                              '-show_data','-of','json',str(output)],capture_output=True,timeout=15)
        assert probe.returncode==0,probe.stderr.decode(errors='replace')
        video=json.loads(probe.stdout)['streams'][0]
        assert (video['codec_name'],video['width'],video['height'],int(video['nb_read_frames']))==(codec,320,180,30)
        if codec=='hevc':
            assert video['codec_tag_string']=='hvc1'
            exact_codec=media.hevc_codec_string(video['extradata'])
            assert exact_codec.startswith('hvc1.')
            elementary=folder/'actual-rtsp-style-extradata.hevc'
            converted=subprocess.run([ffmpeg_binary,'-hide_banner','-loglevel','error','-y','-i',str(source),'-c:v','copy',
                                      '-bsf:v','hevc_mp4toannexb','-f','hevc',str(elementary)],capture_output=True,timeout=15)
            assert converted.returncode==0
            annex_probe=subprocess.run([ffprobe,'-v','error','-show_entries','stream=extradata','-show_data','-of','json',str(elementary)],capture_output=True,timeout=15)
            assert annex_probe.returncode==0
            assert media.hevc_codec_string(json.loads(annex_probe.stdout)['streams'][0]['extradata'])==exact_codec
        def decoded_hashes(path):
            result=subprocess.run([ffmpeg_binary,'-hide_banner','-loglevel','error','-i',str(path),'-map','0:v:0','-f','framemd5','-'],capture_output=True,timeout=20)
            assert result.returncode==0,result.stderr.decode(errors='replace')
            return [line.rsplit(',',1)[-1].strip() for line in result.stdout.decode().splitlines() if line and not line.startswith('#')]
        assert decoded_hashes(source)==decoded_hashes(output)
    finally:
        manager.stop_all()
    assert not manager.streams


def netip_video(payload, stamp):
    value = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
    packed = ((value.year - 2000) << 26 | value.month << 22 | value.day << 17 |
              value.hour << 12 | value.minute << 6 | value.second)
    return (b'\x00\x00\x01\xfc' +
            struct.pack('<BBBBII', 2, FPS, WIDTH // 8, HEIGHT // 8, packed, len(payload)) +
            payload)


@pytest.fixture
def mux_pipeline(monkeypatch, ffmpeg_binary, synthetic_clip):
    folder, payload = synthetic_clip
    camera = {'id': 'synthetic-ch3', 'name': 'Synthetic camera', 'protocol': 'dvrip',
              'ip': '192.0.2.10', 'port': 34567, 'channel': 2,
              'username': 'test-operator', 'password': 'test-encrypted-value'}
    records = [
        {'FilePath': '/synthetic/003/first.h264', 'BeginTime': START, 'EndTime': MIDDLE, 'Channel': 2},
        {'FilePath': '/synthetic/003/second.h264', 'BeginTime': MIDDLE, 'EndTime': END, 'Channel': 2},
    ]
    rt = SimpleNamespace(
        store=SimpleNamespace(base_dir=folder,revision=0,get_users=lambda:[{'role':'viewer','username':'synthetic-viewer'}]),
        current_user=lambda: {'role': 'viewer','username':'synthetic-viewer'},
        get_camera=lambda camera_id: camera if camera_id == camera['id'] else None,
        can_access_camera=lambda user, camera_id: camera_id == camera['id'],
        can_access_archive=lambda user: True,
        can_export_archive=lambda user=None:True,
        enc_pwd=lambda password: password,
        dec_pwd=lambda password: 'synthetic-password',
        audit=Mock(),
        settings=lambda: {'resources': {'max_live_streams': 2, 'max_archive_streams': 1,
            'archive_buffer_mb': 2, 'archive_idle_seconds': 30, 'ffmpeg_threads': 1}},
    )
    app = Flask(__name__)
    app.secret_key = 'synthetic-test-session-secret'
    app.config['TESTING'] = True
    app.extensions['vwshub'] = rt
    service = media.register_media(app, rt)
    connections, calls, commands = [], [], []

    def open_connection(cam_info, password, on_open=None):
        assert cam_info['id'] == camera['id'] and password == 'synthetic-password'
        connection = Mock()
        connections.append(connection)
        if on_open:
            assert on_open(connection) is not False
        return connection

    def chunks(connection, path, start, end, mode='files', channel=0, cancel=None):
        assert connection in connections
        assert mode == 'files' and channel == 2
        calls.append((path, start, end, channel))
        record = next(item for item in records if item['FilePath'] == path)
        # Emulate ByName firmware returning the whole file despite StartTime.
        wire = netip_video(payload, record['BeginTime'])
        for offset in range(0, len(wire), 4093):
            if cancel is not None and cancel.is_set():
                return
            yield wire[offset:offset + 4093]

    real_which = shutil.which
    real_popen = subprocess.Popen

    def launch(command, *args, **kwargs):
        # Observe arguments without replacing the process or its real pipes.
        if '-movflags' in command:
            commands.append(list(command))
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(media.shutil, 'which', lambda command: ffmpeg_binary if command == 'ffmpeg' else real_which(command))
    monkeypatch.setattr(media, 'open_dvr_connection', open_connection)
    monkeypatch.setattr(media, 'dvrip_playback_chunks', chunks)
    monkeypatch.setattr(media.subprocess, 'Popen', launch)
    try:
        yield SimpleNamespace(app=app, service=service, camera=camera, records=records,
            folder=folder, connections=connections, calls=calls, commands=commands,
            ffmpeg=ffmpeg_binary)
    finally:
        service.stop_all()
        assert service.active_archives == 0
        assert not service.operations


def read_response(pipeline, start=START, end=END, attachment=False, export_format=None):
    with pipeline.app.test_request_context('/?play_id=mux_integration_123'):
        session['archive_consumer'] = 'synthetic-viewer'
        response = media.create_archive_response(
            pipeline.camera, pipeline.records, start, end, as_attachment=attachment, export_format=export_format)
        assert not isinstance(response, tuple), response
        assert response.status_code == 200
        assert pipeline.service.active_archives == 1
        try:
            content = response.get_data()
            headers = dict(response.headers)
        finally:
            response.close()
        assert pipeline.service.active_archives == 0
        assert not pipeline.service.operations
    assert pipeline.connections
    assert all(connection.close.called for connection in pipeline.connections)
    return content, headers


def decode_mp4(pipeline, content):
    output = pipeline.folder / (uuid.uuid4().hex + '.mp4')
    output.write_bytes(content)
    result = subprocess.run([
        pipeline.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostats',
        '-i', str(output), '-map', '0:v:0', '-an', '-vsync', '0',
        '-pix_fmt', 'gray', '-f', 'rawvideo', '-progress', 'pipe:2', 'pipe:1',
    ], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    pixels_per_frame = WIDTH * HEIGHT
    assert len(result.stdout) % pixels_per_frame == 0
    progress = result.stderr.decode(errors='replace')
    times = re.findall(r'^out_time_us=(\d+)$', progress, re.MULTILINE)
    assert times, progress
    return len(result.stdout) // pixels_per_frame, int(times[-1]) / 1_000_000


def assert_fragmented_mp4(content):
    boxes = []
    offset = 0
    while offset + 8 <= len(content):
        size, kind = struct.unpack_from('>I4s', content, offset)
        header = 8
        if size == 1:
            assert offset + 16 <= len(content)
            size = struct.unpack_from('>Q', content, offset + 8)[0]
            header = 16
        elif size == 0:
            size = len(content) - offset
        assert size >= header and offset + size <= len(content)
        boxes.append(kind)
        offset += size
    assert offset == len(content)
    assert boxes[0] == b'ftyp'
    assert b'moov' in boxes and b'moof' in boxes and b'mdat' in boxes


def test_two_dvr_files_remux_to_six_seconds_and_ninety_decodable_frames(mux_pipeline):
    pipeline = mux_pipeline
    content, headers = read_response(pipeline)
    assert_fragmented_mp4(content)
    frame_count, seconds = decode_mp4(pipeline, content)
    assert frame_count == 90
    # FFmpeg builds report either the end time or the last frame's PTS. Allow
    # one frame plus microsecond-report rounding; frame counts remain exact.
    assert seconds == pytest.approx(6, abs=1 / FPS + 0.001)
    assert headers['X-VWSHub-Archive-Channel'] == '2'
    assert headers['X-VWSHub-Archive-Frame-Rate'] == str(FPS)
    assert pipeline.calls == [
        (pipeline.records[0]['FilePath'], START, MIDDLE, 2),
        (pipeline.records[1]['FilePath'], MIDDLE, END, 2),
    ]


def test_download_trims_selected_cross_file_range_and_releases_slot(mux_pipeline):
    pipeline = mux_pipeline
    start, end = '2026-10-29 12:00:02', '2026-10-29 12:00:05'
    content, headers = read_response(pipeline, start, end, attachment=True)
    assert_fragmented_mp4(content)
    assert headers['Content-Disposition'].startswith('attachment;')
    assert '20261029_120002-20261029_120005.mp4' in headers['Content-Disposition']
    assert len(pipeline.commands) == 1
    command = pipeline.commands[0]
    assert command.count("-threads") == 2
    assert all(command[i + 1] == "1" for i, value in enumerate(command) if value == "-threads")
    assert "-rw_timeout" not in command
    assert float(command[command.index('-t') + 1]) == 3
    assert float(command[command.index('-ss') + 1]) == 2
    frame_count, seconds = decode_mp4(pipeline, content)
    assert frame_count == 45
    assert seconds == pytest.approx(3, abs=1 / FPS + 0.001)
    assert pipeline.calls == [
        (pipeline.records[0]['FilePath'], start, MIDDLE, 2),
        (pipeline.records[1]['FilePath'], MIDDLE, end, 2),
    ]


def test_closing_real_mux_response_before_consuming_releases_slot(mux_pipeline):
    pipeline = mux_pipeline
    with pipeline.app.test_request_context('/?play_id=mux_early_close_123'):
        session['archive_consumer'] = 'synthetic-viewer'
        response = media.create_archive_response(pipeline.camera, pipeline.records, START, END)
        assert not isinstance(response, tuple), response
        assert pipeline.service.active_archives == 1
        response.close()
        response.close()  # WSGI close and cancellation may both invoke cleanup.
        assert pipeline.service.active_archives == 0
        assert not pipeline.service.operations
    assert all(connection.close.called for connection in pipeline.connections)


@pytest.mark.parametrize('export_format,extension,container,codec',[('avi','avi','avi','mpeg4'),('original','h264','h264','h264')])
def test_real_additional_exports_are_valid_containers_and_decodable(mux_pipeline,export_format,extension,container,codec):
    pipeline=mux_pipeline
    content,headers=read_response(pipeline,attachment=True,export_format=export_format)
    assert headers['Content-Disposition'].endswith('.'+extension+'"')
    if export_format=='avi':assert content[:4]==b'RIFF' and content[8:12]==b'AVI '
    else:assert content.startswith((b'\x00\x00\x00\x01',b'\x00\x00\x01'))
    output=pipeline.folder/(uuid.uuid4().hex+'.'+extension);output.write_bytes(content)
    probe=shutil.which('ffprobe')
    if probe:
        result=subprocess.run([probe,'-v','error','-show_entries','format=format_name:stream=codec_name','-of','json',str(output)],capture_output=True,timeout=20)
        assert result.returncode==0,result.stderr
        metadata=json.loads(result.stdout)
        assert metadata['format']['format_name']==container
        assert metadata['streams'][0]['codec_name']==codec
    frame_count,_=decode_mp4(pipeline,content)
    assert frame_count==90


def test_original_hevc_is_real_h265_elementary_stream(mux_pipeline,monkeypatch):
    pipeline=mux_pipeline
    clip=pipeline.folder/'source.hevc'
    result=subprocess.run([pipeline.ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i',f'testsrc=size={WIDTH}x{HEIGHT}:rate={FPS}:duration=3',
        '-an','-c:v','libx265','-pix_fmt','yuv420p','-threads','1','-x265-params','pools=1:frame-threads=1:log-level=error','-f','hevc',str(clip)],capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    def chunks(_connection,path,left,right,**kwargs):
        wire=bytearray(netip_video(clip.read_bytes(),START));wire[4]=3
        yield bytes(wire)
    monkeypatch.setattr(media,'dvrip_playback_chunks',chunks)
    pipeline.records=pipeline.records[:1]
    content,headers=read_response(pipeline,end=MIDDLE,attachment=True,export_format='original')
    assert headers['Content-Disposition'].endswith('.h265"') and headers['Content-Type'].startswith('video/h265')
    assert content.startswith((b'\x00\x00\x00\x01',b'\x00\x00\x01'))
    output=pipeline.folder/'export.h265';output.write_bytes(content)
    probe=shutil.which('ffprobe')
    if probe:
        checked=subprocess.run([probe,'-v','error','-show_entries','stream=codec_name','-of','json',str(output)],capture_output=True,timeout=20)
        assert checked.returncode==0 and json.loads(checked.stdout)['streams'][0]['codec_name']=='hevc'
    frames,_=decode_mp4(pipeline,content)
    assert frames==45


def test_real_live_audio_pipeline_transcodes_alaw_to_aac_hls(mux_pipeline,monkeypatch):
    pipeline=mux_pipeline
    source=pipeline.folder/'microphone.wav'
    generated=subprocess.run([pipeline.ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i','sine=frequency=800:sample_rate=8000:duration=3','-c:a','pcm_alaw',str(source)],capture_output=True,timeout=20)
    assert generated.returncode==0,generated.stderr
    observed=[];real_popen=subprocess.Popen
    def launch(command,*args,**kwargs):
        observed.append(list(command))
        local=list(command)
        if '-rtsp_transport' in local:
            transport=local.index('-rtsp_transport');del local[transport:transport+2]
            local[local.index('-i')+1]=str(source)
        return real_popen(local,*args,**kwargs)
    monkeypatch.setattr(media.subprocess,'Popen',launch)
    with pipeline.app.test_request_context():
        item=pipeline.service.live.ensure(pipeline.camera['id'],'audio-main','synthetic-viewer:audio')
        assert item['process'].wait(timeout=20)==0
        playlist=item['directory']/'index.m3u8'
        assert playlist.exists() and '#EXTINF:' in playlist.read_text()
        segments=list(item['directory'].glob('seg_*.ts'))
        assert segments
        probe=shutil.which('ffprobe')
        if probe:
            checked=subprocess.run([probe,'-v','error','-show_entries','stream=codec_name,codec_type','-of','json',str(segments[0])],capture_output=True,timeout=20)
            assert checked.returncode==0
            streams=json.loads(checked.stdout)['streams']
            assert any(stream['codec_name']=='aac' and stream['codec_type']=='audio' for stream in streams)
            assert not any(stream['codec_type']=='video' for stream in streams)
        pipeline.service.live.release(pipeline.camera['id'],'audio-main','synthetic-viewer:audio')
        assert not pipeline.service.live.streams
    assert '0:a:0' in observed[0] and '-vn' in observed[0]
