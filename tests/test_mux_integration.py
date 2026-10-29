"""Real FFmpeg archive remux regressions with synthetic, offline DVRIP input.

Set FFMPEG_BINARY or install ffmpeg in PATH to run these tests. No device is
contacted: only the DVR connection and its NETIP download are replaced. Linux CI
can install ffmpeg with apt; no ffprobe or pytest temporary-directory fixture is
required. Scratch data lives outside the distributable project.
"""
from __future__ import annotations

import os
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
        store=SimpleNamespace(base_dir=folder),
        current_user=lambda: {'role': 'viewer'},
        get_camera=lambda camera_id: camera if camera_id == camera['id'] else None,
        can_access_camera=lambda user, camera_id: camera_id == camera['id'],
        can_access_archive=lambda user: True,
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


def read_response(pipeline, start=START, end=END, attachment=False):
    with pipeline.app.test_request_context('/?play_id=mux_integration_123'):
        session['archive_consumer'] = 'synthetic-viewer'
        response = media.create_archive_response(
            pipeline.camera, pipeline.records, start, end, as_attachment=attachment)
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
