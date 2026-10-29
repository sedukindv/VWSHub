"""Media regressions use synthetic NETIP packets and never contact real devices."""
import io
import json
import socket
import struct
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask,session
from hub import media


@pytest.fixture
def app_media():
    folder=Path(__file__).parent.parent.parent/'.media-tests'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    cameras={f'ch{n+1}':{'id':f'ch{n+1}','name':f'Camera {n+1}','protocol':'dvrip','ip':'192.0.2.10','port':34567,'channel':n,'username':'operator','password':'encrypted'} for n in range(3)}
    state={'logged':True,'archive':True,'visible':set(cameras)}
    rt=SimpleNamespace(store=SimpleNamespace(base_dir=folder),current_user=lambda:{'role':'viewer'} if state['logged'] else None,
        get_camera=lambda id:cameras.get(id),can_access_camera=lambda user,id:id in state['visible'],can_access_archive=lambda user:state['archive'],
        enc_pwd=lambda p:p,dec_pwd=lambda p:'test-password',audit=Mock(),settings=lambda:{'resources':{'max_live_streams':2,'max_archive_streams':2,'archive_buffer_mb':1,'archive_idle_seconds':30}})
    app=Flask(__name__);app.secret_key='test-only';app.config['TESTING']=True;app.extensions['vwshub']=rt
    service=media.register_media(app,rt)
    yield app,service,state,cameras
    service.stop_all()


@pytest.mark.parametrize('path',['/api/recordings?cam_id=ch2','/api/playback?cam_id=ch2','/api/download?cam_id=ch2','/api/archive/audio?cam_id=ch2','/api/archive/capabilities?cam_id=ch2','/live/ch2/main/index.m3u8','/live/ch2/main/seg_000001.ts','/api/cameras/ch2/snapshot'])
def test_every_media_route_requires_camera_visibility(app_media,path):
    app,service,state,_=app_media;state['visible']={'ch1'}
    assert app.test_client().get(path).status_code==403


@pytest.mark.parametrize('path',['/api/recordings','/api/playback','/api/download','/api/archive/audio','/api/archive/capabilities'])
def test_archive_permission_is_independent_of_live_group_visibility(app_media,path):
    app,_,state,_=app_media;state['archive']=False
    assert app.test_client().get(path+'?cam_id=ch1').status_code==403


def test_anonymous_stream_cannot_read_even_cached_segment(app_media):
    app,_,state,_=app_media;state['logged']=False
    assert app.test_client().get('/live/ch1/main/seg_000001.ts').status_code==401


def item(path,start='2026-10-29 12:00:00',end='2026-10-29 12:10:00',channel=0):
    return {'FileName':path,'FilePath':path,'BeginTime':start,'EndTime':end,'Channel':channel}


def test_stale_channel_field_does_not_relabel_channel_three_as_first():
    result=media.normalize_recordings([item('/idea0/2026-10-29/003/12.00.00-12.10.00.h264')],channel=2)
    assert result[0]['Channel']==2
    assert media.normalize_recordings([item('/plain/clip.h264',channel=0)],channel=2)[0]['Channel']==2


def test_query_filters_other_camera_paths_and_sorts_deduplicates(app_media,monkeypatch):
    app,service,_,cams=app_media
    dvr=Mock();dvr.list_local_files.return_value=[item('/idea0/2026-10-29/001/first.h264'),item('/idea0/2026-10-29/003/third.h264'),item('/idea0/2026-10-29/003/third.h264'),None]
    monkeypatch.setattr(media,'dvr_connect',lambda cam:dvr)
    with app.test_request_context():records=service.query_files(cams['ch3'],'2026-10-29 12:00:00','2026-10-29 13:00:00')
    assert len(records)==1 and records[0]['Channel']==2
    dvr.list_local_files.assert_called_once_with('2026-10-29 12:00:00','2026-10-29 13:00:00','h264',channel=2)
    dvr.close.assert_called_once()


def test_resolve_rejects_an_explicit_other_channel_even_for_same_recorder(app_media):
    app,service,_,cams=app_media
    with app.test_request_context(),pytest.raises(ValueError,match='другому каналу'):
        service.resolve(cams['ch3'],'2026-10-29 12:00:00','2026-10-29 13:00:00','/idea0/2026-10-29/001/private.h264')


def test_partial_socket_payload_survives_network_timeouts():
    class Bursty:
        parts=[b'AB',socket.timeout(),b'C',socket.timeout(),b'DEF']
        def recv(self,size):
            value=self.parts.pop(0)
            if isinstance(value,Exception):raise value
            return value
    assert media.recv_exact(Bursty(),6,max_idle_timeouts=2)==b'ABCDEF'


def test_cancel_interrupts_pending_socket_read():
    cancel=threading.Event();cancel.set()
    with pytest.raises(ConnectionAbortedError):media.recv_exact(Mock(),20,cancel)


def test_single_authenticated_socket_download_preserves_exact_file_and_channel(monkeypatch):
    path='/idea0/2026-10-29/003/12.00.00-12.10.00.h264'
    pack=lambda kind,data=b'':media.DVRIP_HEADER.pack(255,0,7,1,kind,len(data))+data
    payload=bytearray(pack(1421,b'')+pack(1426,b'channel-three')+pack(1423))
    def recv(size):part=bytes(payload[:size]);del payload[:size];return part
    cam=SimpleNamespace(session=7,packet_count=1,socket=SimpleNamespace(recv=recv),busy=threading.Lock(),socket_send=Mock(),send=Mock(return_value={'Ret':100}))
    monkeypatch.setattr(media.socket,'create_connection',lambda *a,**k:pytest.fail('must not open a second data connection'))
    assert list(media.dvrip_playback_chunks(cam,path,'2026-10-29 12:01:00','2026-10-29 12:10:00',channel=2))==[b'channel-three']
    claim=cam.send.call_args_list[0].args[1]['OPPlayBack']
    assert claim['Parameter']['PlayMode']=='ByName' and claim['Parameter']['FileName']==path and claim['Parameter']['Channel']==2
    start=json.loads(cam.socket_send.call_args.args[0][20:].rstrip(b'\0\n'))
    assert start['OPPlayBack']['Action']=='DownloadStart' and start['OPPlayBack']['Parameter']['Channel']==2


def video_frame(payload=b'\0\0\0\1\x65\x88',codec=2,fps=15):
    return b'\0\0\1\xfc'+struct.pack('<BBBBII',codec,fps,160,90,0,len(payload))+payload


def test_video_extraction_never_passes_audio_to_default_video_pipeline():
    audio=b'\0\0\1\xfa'+struct.pack('<BBH',0x0e,0,3)+b'ABC'
    assert list(media.iter_dvr_video_frames([audio+video_frame()]))==[('h264',b'\0\0\0\1\x65\x88')]
    assert list(media.iter_dvr_audio_frames([video_frame()+audio]))==[('alaw',b'ABC')]


def test_unknown_archive_audio_codec_is_rejected_before_playback():
    audio=b'\0\0\1\xfa'+struct.pack('<BBH',1,0,3)+b'ABC'
    with pytest.raises(ValueError,match='G.711'):list(media.iter_dvr_audio_frames([audio]))


def test_corrupt_hevc_service_nal_cannot_break_following_good_frame():
    key=b'\0\0\0\1\x26\x01\xaa';bad=b'\0\0\0\1\x11\x01'+b'\0'*121;good=b'\0\0\0\1\x02\x01\xbb'
    delta=lambda p:b'\0\0\1\xfd'+struct.pack('<I',len(p))+p
    assert list(media.iter_dvr_video_frames([video_frame(key,3)+delta(bad)+delta(good)]))==[('hevc',key),('hevc',good)]


def test_microphone_capability_uses_selected_channel_and_explicit_enable(app_media,monkeypatch):
    app,service,_,cams=app_media;dvr=Mock()
    dvr.get_encode_info.return_value=[{'MainFormat':{'AudioEnable':False,'Audio':{'Compression':'G711_ALAW'}}},{'MainFormat':{'AudioEnable':True,'Audio':{'Compression':'G711_ALAW'}}}]
    monkeypatch.setattr(media,'dvr_connect',lambda _:dvr)
    with app.test_request_context():
        assert service.audio_capabilities(cams['ch1'])['supported'] is False
        assert service.audio_capabilities(cams['ch2'])['supported'] is True


def test_multi_file_export_resolves_selected_range_instead_of_first_file_only(app_media,monkeypatch):
    app,service,_,_=app_media
    records=[item('/a.h264'),item('/b.h264','2026-10-29 12:10:00','2026-10-29 12:20:00')]
    resolve=Mock(return_value=records);monkeypatch.setattr(service,'resolve',resolve)
    response=Mock(return_value=('export-accepted',200));monkeypatch.setattr(media,'create_archive_response',response)
    result=app.test_client().get('/api/download',query_string={'cam_id':'ch2','start':'2026-10-29 12:05:00','end':'2026-10-29 12:15:00','mode':'time','path':''})
    assert result.status_code==200
    assert response.call_args.args[0]['channel']==1 and response.call_args.args[1]==records
    assert response.call_args.args[4] is True


def test_archive_slot_limit_rejects_before_opening_dvr(app_media,monkeypatch):
    app,service,_,cams=app_media;monkeypatch.setattr(media.shutil,'which',lambda _:'ffmpeg')
    service.active_archives=2
    with app.test_request_context():
        _,code=media.create_archive_response(cams['ch1'],[],'2026-10-29 12:00:00','2026-10-29 12:10:00')
    assert code==429 and service.active_archives==2


def test_cancelled_request_tombstone_prevents_late_connection_and_resource_reservation(app_media,monkeypatch):
    app,service,_,cams=app_media;monkeypatch.setattr(media.shutil,'which',lambda _:'ffmpeg')
    connect=Mock(side_effect=AssertionError('cancelled request must not connect'));monkeypatch.setattr(media,'DVRIPCam',connect)
    with app.test_request_context('/api/playback?play_id=cancelled-request-123'):
        session['archive_consumer']='session-A'
        service.cancel_operation('session-A','cancelled-request-123','ch1')
        _,code=media.create_archive_response(cams['ch1'],[],'2026-10-29 12:00:00','2026-10-29 12:10:00')
    assert code==409 and service.active_archives==0;connect.assert_not_called()


def test_archive_stop_cannot_cancel_a_different_browser_session(app_media):
    app,service,_,_=app_media
    other=Mock();service.operations[('session-B','same-play-id-123')]={'camera':'ch1','cancel':other}
    client=app.test_client()
    with client.session_transaction() as values:values['archive_consumer']='session-A'
    assert client.post('/api/archive/stop',json={'cam_id':'ch1','play_id':'same-play-id-123'}).status_code==200
    other.assert_not_called();assert ('session-A','same-play-id-123') in service.cancelled
    service.operations.clear()


def test_archive_stop_checks_group_scope_before_registering_a_cancellation(app_media):
    app,service,state,_=app_media;state['visible']={'ch1'}
    response=app.test_client().post('/api/archive/stop',json={'cam_id':'ch2','play_id':'same-play-id-123'})
    assert response.status_code==403 and not service.cancelled


@pytest.mark.parametrize('fps',[15,20,0,200])
def test_stream_copy_flushes_short_fragments_and_closes_reserved_slot(app_media,monkeypatch,fps):
    app,service,_,cams=app_media
    class Proc:
        def __init__(self):self.stdin=io.BytesIO();self.stdout=io.BytesIO(b'MP4-HEADER-MEDIA');self.stderr=io.BytesIO();self.code=None
        def poll(self):return self.code
        def wait(self,timeout=None):self.code=0
        def terminate(self):self.code=-15
        def kill(self):self.code=-9
    launch=Mock(return_value=Proc());cam=Mock();cam.login.return_value=True
    monkeypatch.setattr(media,'DVRIPCam',Mock(return_value=cam));monkeypatch.setattr(media.shutil,'which',lambda _:'test-ffmpeg');monkeypatch.setattr(media.subprocess,'Popen',launch)
    monkeypatch.setattr(media,'dvrip_playback_chunks',lambda *a,**k:iter([video_frame(fps=fps)]))
    with app.test_request_context():
        response=media.create_archive_response(cams['ch2'],[item('/same-channel.h264')],'2026-10-29 12:00:00','2026-10-29 12:10:00')
        assert response.get_data()==b'MP4-HEADER-MEDIA';response.close();response.close()
    cmd=launch.call_args.args[0]
    assert cmd[cmd.index('-c:v')+1]=='copy' and '-an' in cmd and '-re' not in cmd
    assert cmd[cmd.index('-frag_duration')+1]=='1000000' and cmd[cmd.index('-flush_packets')+1]=='1'
    if 1<=fps<=120:
        assert cmd.index('-framerate')<cmd.index('-i') and cmd[cmd.index('-framerate')+1]==str(fps)
        assert response.headers['X-VWSHub-Archive-Frame-Rate']==str(fps)
    else:assert '-framerate' not in cmd
    assert '-r' not in cmd
    assert service.active_archives==0
    cam.close.assert_called_once()


def test_large_frame_partial_pipe_writes_keep_every_byte():
    accepted=bytearray()
    class PartialPipe:
        def write(self,payload):
            part=bytes(payload[:3]);accepted.extend(part);return len(part)
    assert media._write_all(PartialPipe(),b'complete-video-frame') is True
    assert accepted==b'complete-video-frame'
    cancelled=threading.Event();cancelled.set()
    assert media._write_all(PartialPipe(),b'not-written',cancelled) is False
    assert accepted==b'complete-video-frame'


def test_paused_client_resumes_with_all_final_fragments(app_media,monkeypatch):
    """A full bounded output queue must not close stdout at the old 3s limit."""
    app,service,_,cams=app_media
    payload=b'mp4-fragment-'*250000
    full_buffer=threading.Event()
    class Output(io.BytesIO):
        def read(self,size=-1):
            result=super().read(size)
            if self.tell()>=34*32768:full_buffer.set()
            return result
    class Proc:
        def __init__(self):self.stdin=io.BytesIO();self.stdout=Output(payload);self.stderr=io.BytesIO();self.code=None
        def poll(self):return self.code
        def wait(self,timeout=None):self.code=0;return 0
        def terminate(self):self.code=-15
        def kill(self):self.code=-9
    proc=Proc();cam=Mock();cam.login.return_value=True
    monkeypatch.setattr(media,'DVRIPCam',Mock(return_value=cam));monkeypatch.setattr(media.shutil,'which',lambda _:'test-ffmpeg');monkeypatch.setattr(media.subprocess,'Popen',lambda *a,**k:proc)
    monkeypatch.setattr(media,'dvrip_playback_chunks',lambda *a,**k:iter([video_frame()]))
    with app.test_request_context():
        response=media.create_archive_response(cams['ch2'],[item('/same-channel.h264')],'2026-10-29 12:00:00','2026-10-29 12:10:00')
        try:
            assert full_buffer.wait(2), 'synthetic stream did not fill the bounded queue'
            threading.Event().wait(3.25)
            assert response.get_data()==payload
        finally:response.close()
    assert service.active_archives==0
