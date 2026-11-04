"""Media regressions use synthetic NETIP packets and never contact real devices."""
import io
import json
import socket
import struct
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask,session
from hub import media


def test_live_leases_are_isolated_between_tabs_of_the_same_account(app_media,monkeypatch):
    app,service,_,_=app_media
    app.extensions['vwshub'].current_user=lambda:{'role':'viewer','username':'same_account'}
    directory=service.live.root/'tab-test';directory.mkdir()
    (directory/'index.m3u8').write_text('#EXTM3U\n#EXTINF:2,\nseg_000001.ts\n')
    (directory/'seg_000001.ts').write_bytes(b'synthetic segment')
    process=Mock();process.poll.return_value=0
    item={'process':process,'directory':directory,'leases':{}}
    def ensure(cam,stream,consumer,container="ts"):
        item['leases'][consumer]=time.monotonic();service.live.streams[(cam,stream,container)]=item;return item
    monkeypatch.setattr(service.live,'ensure',ensure)
    client=app.test_client();one='a'*32;two='b'*32
    result=client.get('/live/ch1/main/index.m3u8?consumer='+one)
    assert result.status_code==200 and ('seg_000001.ts?consumer='+one) in result.get_data(as_text=True)
    assert client.get('/live/ch1/main/index.m3u8?consumer='+two).status_code==200
    assert client.post('/api/live/stop',json={'cam_id':'ch1','stream':'main','consumer':one}).status_code==200
    assert ('ch1','main','ts') in service.live.streams and set(item['leases'])=={'same_account:'+two}
    assert client.get('/live/ch1/main/seg_000001.ts?consumer='+two).status_code==200
    assert client.post('/api/live/stop',json={'cam_id':'ch1','stream':'main','consumer':two}).status_code==200
    assert ('ch1','main','ts') not in service.live.streams


def test_connection_test_uses_the_edited_rtsp_host_and_path(app_media,monkeypatch):
    app,_,_,_=app_media
    app.extensions['vwshub'].current_user=lambda:{'role':'admin','username':'owner'}
    monkeypatch.setattr(media.shutil,'which',lambda _: 'synthetic-ffmpeg')
    run=Mock(return_value=SimpleNamespace(returncode=0));monkeypatch.setattr(media.subprocess,'run',run)
    response=app.test_client().post('/api/cameras/test',json={'id':'ch1','protocol':'onvif','ip':'192.0.2.10','port':80,
        'rtsp_host':'198.51.100.88','rtsp_path':'/new-path','rtsp_port':8554})
    assert response.status_code==200 and response.json['ok'] is True
    assert '@198.51.100.88:8554/new-path' in run.call_args.args[0][run.call_args.args[0].index('-i')+1]


@pytest.fixture
def app_media():
    folder=Path(__file__).parent.parent.parent/'.media-tests'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    cameras={f'ch{n+1}':{'id':f'ch{n+1}','name':f'Camera {n+1}','protocol':'dvrip','ip':'192.0.2.10','port':34567,'channel':n,'username':'operator','password':'encrypted'} for n in range(3)}
    state={'logged':True,'archive':True,'visible':set(cameras)}
    rt=SimpleNamespace(store=SimpleNamespace(base_dir=folder,revision=0,get_users=lambda:[rt.current_user()] if rt.current_user() else []),current_user=lambda:{'role':'viewer','username':'operator'} if state['logged'] else None,
        get_camera=lambda id:cameras.get(id),can_access_camera=lambda user,id:id in state['visible'],can_access_archive=lambda user:state['archive'],can_export_archive=lambda user=None:state.get('export',True),
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


def test_archive_generator_stops_before_next_chunk_after_scope_revocation(app_media,monkeypatch):
    app,service,state,cams=app_media
    class Proc:
        def __init__(self):self.stdin=io.BytesIO();self.stdout=io.BytesIO(b'fragment'*10000);self.stderr=io.BytesIO();self.code=None
        def poll(self):return self.code
        def wait(self,timeout=None):self.code=0;return 0
        def terminate(self):self.code=-15
        def kill(self):self.code=-9
    cam=Mock();cam.login.return_value=True
    monkeypatch.setattr(media,'DVRIPCam',Mock(return_value=cam));monkeypatch.setattr(media.shutil,'which',lambda _:'test-ffmpeg');monkeypatch.setattr(media.subprocess,'Popen',lambda *a,**k:Proc())
    monkeypatch.setattr(media,'dvrip_playback_chunks',lambda *a,**k:iter([video_frame()]))
    with app.test_request_context():
        response=media.create_archive_response(cams['ch2'],[item('/same-channel.h264')],'2026-10-29 12:00:00','2026-10-29 12:10:00')
        iterator=iter(response.response)
        try:
            assert next(iterator)
            state['visible'].remove('ch2');service.runtime.store.revision+=1
            assert list(iterator)==[]
        finally:response.close()
    assert service.active_archives==0
    cam.close.assert_called_once()


def test_snapshot_rechecks_scope_after_slow_device_response(app_media,monkeypatch):
    app,_,state,_=app_media
    monkeypatch.setattr(media.shutil,'which',lambda _:'test-ffmpeg')
    def capture(*args,**kwargs):
        state['visible'].clear()
        return SimpleNamespace(returncode=0,stdout=b'synthetic-frame')
    monkeypatch.setattr(media.subprocess,'run',capture)
    assert app.test_client().get('/api/cameras/ch1/snapshot').status_code==403


def test_live_audio_uses_confirmed_rtsp_track_not_archive_audio_configuration(app_media,monkeypatch):
    app,service,state,cameras=app_media
    state['archive']=False
    run=Mock(return_value=SimpleNamespace(returncode=0,stdout=b'{"streams":[{"codec_type":"audio","codec_name":"pcm_alaw"}]}'))
    monkeypatch.setattr(media.shutil,'which',lambda name:'test-'+name)
    monkeypatch.setattr(media.subprocess,'run',run)
    with app.test_request_context():
        result=service.live_audio_capabilities(cameras['ch1'],'sub')
        assert result['supported'] is True and result['kind']=='live_audio' and result['codec']=='pcm_alaw'
        service.live_audio_capabilities(cameras['ch1'],'sub')
        assert run.call_count==1
        command=run.call_args.args[0]
        assert '-show_entries' in command and 'stream=1.sdp' in command[command.index('-i')+1]
        assert '-rw_timeout' not in command
        run.return_value.stdout=b'{"streams":[]}'
        assert service.live_audio_capabilities(cameras['ch1'],'main')['supported'] is False


def test_video_and_audio_share_one_factual_probe_but_profiles_and_channels_do_not(app_media,monkeypatch):
    app,service,_,cams=app_media
    run=Mock(return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'streams':[
        {'codec_type':'video','codec_name':'hevc','width':1920,'height':1080,'avg_frame_rate':'25/1'},
        {'codec_type':'audio','codec_name':'aac'}]}).encode()))
    monkeypatch.setattr(media.shutil,'which',lambda name:'test-'+name)
    monkeypatch.setattr(media.subprocess,'run',run)
    with app.test_request_context():
        video=service.live_video_capabilities(cams['ch1'],'main')
        assert video['codec']=='hevc' and video['container']=='fmp4' and video['framerate']==25
        assert service.live_audio_capabilities(cams['ch1'],'main')['supported'] is True
        assert run.call_count==1
        run.return_value.stdout=b'{"streams":[{"codec_type":"video","codec_name":"h264"}]}'
        assert service.live_video_capabilities(cams['ch1'],'sub')['codec']=='h264'
        assert service.live_video_capabilities(cams['ch2'],'main')['codec']=='h264'
        assert run.call_count==3
        cams['ch1']['rtsp_port']=8554
        assert service.live_video_capabilities(cams['ch1'],'main')['codec']=='h264'
        assert run.call_count==4
    assert '-rw_timeout' not in run.call_args.args[0]


@pytest.mark.parametrize('codec',['h265x','mpeg4','',None])
def test_unknown_video_codec_never_guesses_from_camera_identity(app_media,monkeypatch,codec):
    app,service,_,cams=app_media
    monkeypatch.setattr(service,'live_stream_probe',lambda *args,**kw:{'streams':[{'codec_type':'video','codec_name':codec}]})
    with app.test_request_context():
        result=service.live_video_capabilities(cams['ch1'])
    assert result['codec']=='unknown' and result['codec_string'] is None


def test_parallel_metadata_requests_share_the_same_inflight_rtsp_probe(app_media,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    app,service,_,cams=app_media
    started=threading.Event();resume=threading.Event()
    def probe(*args,**kw):
        started.set();assert resume.wait(3)
        return SimpleNamespace(returncode=0,stdout=b'{"streams":[{"codec_type":"video","codec_name":"hevc"}]}')
    run=Mock(side_effect=probe)
    monkeypatch.setattr(media.shutil,'which',lambda name:'test-'+name)
    monkeypatch.setattr(media.subprocess,'run',run)
    def query():
        with app.test_request_context():return service.live_video_capabilities(cams['ch1'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(query);assert started.wait(2);two=pool.submit(query)
        resume.set()
        assert one.result()['codec']==two.result()['codec']=='hevc'
    assert run.call_count==1 and not service.live_probe_pending


def test_probe_capacity_exhaustion_never_starts_an_extra_process(app_media,monkeypatch):
    app,service,_,cams=app_media
    monkeypatch.setattr(media.shutil,'which',lambda name:'test-'+name)
    service.live_audio_probe_slots=threading.BoundedSemaphore(1)
    service.live_audio_probe_slots.acquire()
    run=Mock();monkeypatch.setattr(media.subprocess,'run',run)
    with app.test_request_context():result=service.live_video_capabilities(cams['ch1'])
    assert result['codec']=='unknown' and 'занята' in result['reason']
    run.assert_not_called();assert not service.live_probe_pending


@pytest.mark.parametrize('probe_state',['missing','failed','timeout'])
def test_only_a_missing_ffprobe_tool_permits_unverified_legacy_ts(app_media,monkeypatch,probe_state):
    app,_,_,_=app_media
    monkeypatch.setattr(media.shutil,'which',lambda name:None if name=='ffprobe' and probe_state=='missing' else 'test-'+name)
    run=Mock(return_value=SimpleNamespace(returncode=1,stdout=b''))
    if probe_state=='timeout':run.side_effect=media.subprocess.TimeoutExpired('synthetic-command',8)
    monkeypatch.setattr(media.subprocess,'run',run)
    response=app.test_client().get('/api/live/capabilities?cam_id=ch1&stream=sub')
    assert response.status_code==200 and response.json['hevc_support'] is False
    video=response.json['live_video']
    assert video['codec']=='unknown' and video['stream']=='sub'
    assert video['legacy_ts_allowed'] is (probe_state=='missing')
    if probe_state=='missing':
        assert video['reason_code']=='ffprobe_unavailable';run.assert_not_called()
    else:assert video['reason_code']!='ffprobe_unavailable'


@pytest.mark.parametrize('path',[
    '/api/live/capabilities?cam_id=ch2',
    '/live/ch2/main/init.mp4?container=fmp4',
    '/live/ch2/main/seg_000001.m4s?container=fmp4'])
def test_hevc_routes_do_not_bypass_visibility(app_media,path):
    app,_,state,_=app_media;state['visible']={'ch1'}
    assert app.test_client().get(path).status_code==403


def test_fmp4_requires_actual_hevc_confirmation_before_starting_stream(app_media,monkeypatch):
    app,service,_,_=app_media
    monkeypatch.setattr(service,'live_video_capabilities',lambda *args:{'codec':'unknown'})
    ensure=Mock();monkeypatch.setattr(service.live,'ensure',ensure)
    response=app.test_client().get('/live/ch1/main/index.m3u8?container=fmp4')
    assert response.status_code==409
    ensure.assert_not_called()


def test_fmp4_manifest_and_init_segments_keep_container_and_tab_lease(app_media,monkeypatch):
    app,service,_,_=app_media
    directory=service.live.root/'fmp4-test';directory.mkdir()
    (directory/'index.m3u8').write_text('#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:2,\nseg_000001.m4s\n')
    (directory/'init.mp4').write_bytes(b'synthetic init');(directory/'seg_000001.m4s').write_bytes(b'synthetic fragment')
    process=Mock();process.poll.return_value=None
    item={'process':process,'directory':directory,'leases':{}}
    def ensure(cam,stream,owner,container):
        item['leases'][owner]=time.monotonic();service.live.streams[(cam,stream,container)]=item;return item
    monkeypatch.setattr(service.live,'ensure',ensure)
    monkeypatch.setattr(service,'live_video_capabilities',lambda *args:{'codec':'hevc'})
    client=app.test_client();consumer='c'*32
    response=client.get('/live/ch1/main/index.m3u8?container=fmp4&consumer='+consumer)
    text=response.get_data(as_text=True)
    assert response.status_code==200 and 'init.mp4?consumer='+consumer+'&container=fmp4' in text
    assert 'seg_000001.m4s?consumer='+consumer+'&container=fmp4' in text
    assert client.get('/live/ch1/main/init.mp4?consumer='+consumer+'&container=fmp4').mimetype=='video/mp4'
    assert client.get('/live/ch1/main/seg_000001.m4s?consumer='+consumer+'&container=fmp4').mimetype=='video/iso.segment'
    assert client.get('/live/ch1/main/seg_000001.m4s?consumer='+consumer).status_code==404
    assert client.post('/api/live/stop',json={'cam_id':'ch1','stream':'main','container':'ts','consumer':consumer}).status_code==200
    assert ('ch1','main','fmp4') in service.live.streams
    assert client.post('/api/live/stop',json={'cam_id':'ch1','stream':'main','container':'fmp4','consumer':consumer}).status_code==200
    assert not service.live.streams


def test_live_container_copy_command_and_stop_all_variants(app_media,monkeypatch):
    app,service,_,_=app_media
    proc=Mock();proc.poll.return_value=None
    launch=Mock(return_value=proc)
    monkeypatch.setattr(media.shutil,'which',lambda name:'test-'+name)
    monkeypatch.setattr(media.subprocess,'Popen',launch)
    with app.test_request_context():
        service.live.ensure('ch1','main','operator:one','fmp4')
        command=launch.call_args.args[0]
        assert command[command.index('-c:v')+1]=='copy' and command[command.index('-hls_segment_type')+1]=='fmp4'
        assert '-rw_timeout' not in command and '-c:a' not in command
        service.live.ensure('ch1','main','operator:two','ts')
        command=launch.call_args.args[0]
        assert '-hls_segment_type' not in command and command[command.index('-c:v')+1]=='copy'
    assert set(service.live.streams)=={('ch1','main','fmp4'),('ch1','main','ts')}
    service.live.stop('ch1','main')
    assert not service.live.streams


def test_hevc_rfc6381_comes_from_profile_tier_level_not_a_generic_guess():
    hvcc=bytes([1,1,0x60,0,0,0,0xb0,0,0,0,0,0,93])
    dump='\n00000000: '+hvcc.hex(' ')+ '  synthetic'
    assert media.hevc_codec_string(dump)=='hvc1.1.6.L93.B0'
    assert media.hevc_codec_string('not extradata') is None


def test_reaper_accounts_for_container_and_keeps_another_active_variant(app_media):
    _,service,_,_=app_media
    manager=media.LiveManager(service.live.root/'isolated-reaper')
    processes=[]
    for container,age in [('ts',0),('fmp4',40)]:
        directory=manager.root/container;directory.mkdir()
        process=Mock();process.poll.return_value=None;processes.append(process)
        manager.streams[('ch1','sub',container)]={'process':process,'directory':directory,'leases':{'operator:tab':time.monotonic()-age}}
    manager.stop_event=SimpleNamespace(wait=Mock(side_effect=[False,True]))
    manager.reap()
    assert set(manager.streams)=={('ch1','sub','ts')}
    processes[1].terminate.assert_called_once();processes[0].terminate.assert_not_called()
    manager.stop_all();assert not manager.streams


def test_permission_revocation_stops_every_container_of_the_source(app_media):
    _,service,state,_=app_media
    for container in ['ts','fmp4']:
        directory=service.live.root/('revoke-'+container);directory.mkdir()
        process=Mock();process.poll.return_value=None
        service.live.streams[('ch1','main',container)]={'process':process,'directory':directory,'leases':{'operator:tab':time.monotonic()}}
    state['visible']=set()
    service.reconcile_permissions()
    assert not service.live.streams


def test_live_audio_missing_probe_and_timeouts_do_not_claim_support(app_media,monkeypatch):
    app,service,_,cameras=app_media
    monkeypatch.setattr(media.shutil,'which',lambda _:None)
    with app.test_request_context():
        assert service.live_audio_capabilities(cameras['ch1'])['supported'] is False
    monkeypatch.setattr(media.shutil,'which',lambda _:'ffprobe')
    monkeypatch.setattr(media.subprocess,'run',Mock(side_effect=media.subprocess.TimeoutExpired('redacted-command',8)))
    with app.test_request_context():
        assert service.live_audio_capabilities(cameras['ch1'])['supported'] is False


def test_live_audio_routes_enforce_visibility_and_positive_confirmation(app_media,monkeypatch):
    app,service,state,_=app_media
    state['visible']={'ch1'}
    probe=Mock(return_value={'supported':False,'reason':'No live audio'})
    monkeypatch.setattr(service,'live_audio_capabilities',probe)
    assert app.test_client().get('/api/live/audio/capabilities?cam_id=ch2').status_code==403
    assert app.test_client().get('/live/ch2/audio-main/index.m3u8').status_code==403
    probe.assert_not_called()
    assert app.test_client().get('/live/ch1/audio-main/index.m3u8').status_code==409
    assert not service.live.streams


def test_audio_hls_uses_audio_only_aac_and_correct_selected_profile(app_media,monkeypatch):
    app,service,_,_=app_media
    proc=Mock();proc.poll.return_value=None
    launch=Mock(return_value=proc)
    monkeypatch.setattr(media.shutil,'which',lambda _:'ffmpeg')
    monkeypatch.setattr(media.subprocess,'Popen',launch)
    with app.test_request_context():
        service.live.ensure('ch1','audio-main','operator:audio-test')
    command=launch.call_args.args[0]
    assert command[command.index('-map')+1]=='0:a:0'
    assert command[command.index('-c:a')+1]=='aac' and '-vn' in command and '-an' not in command
    assert 'stream=0.sdp' in command[command.index('-i')+1]
    service.live.release('ch1','audio-main','operator:audio-test')
    assert not service.live.streams


def test_new_audio_consumer_releases_previous_audio_lease_only(app_media,monkeypatch):
    app,service,_,_=app_media
    owner='operator:'+'a'*32
    process=Mock();process.poll.return_value=None
    directory=service.live.root/'audio-owner-test';directory.mkdir()
    (directory/'index.m3u8').write_text('#EXTM3U\n#EXTINF:2,\nseg_000001.ts\n')
    old={'process':process,'directory':directory,'leases':{owner:time.monotonic(),'operator:another-tab':time.monotonic()}}
    service.live.streams[('ch1','audio-main','ts')]=old
    monkeypatch.setattr(service,'live_audio_capabilities',lambda *args,**kwargs:{'supported':True})
    new_directory=service.live.root/'new-audio-test';new_directory.mkdir()
    (new_directory/'index.m3u8').write_text('#EXTM3U\n#EXTINF:2,\nseg_000001.ts\n')
    monkeypatch.setattr(service.live,'ensure',lambda *args:{'process':process,'directory':new_directory,'leases':{}})
    response=app.test_client().get('/live/ch2/audio-sub/index.m3u8?consumer='+'a'*32)
    assert response.status_code==200
    assert owner not in old['leases'] and 'operator:another-tab' in old['leases']


def test_live_audio_revocation_stops_sole_consumer(app_media):
    app,service,state,_=app_media
    process=Mock();process.poll.return_value=None
    directory=service.live.root/'revoked-audio-test';directory.mkdir()
    service.live.streams[('ch1','audio-main','ts')]={'process':process,'directory':directory,'leases':{'operator:tab':time.monotonic()}}
    state['visible']=set()
    service.reconcile_permissions()
    assert not service.live.streams
    process.terminate.assert_called_once()


def test_audio_live_permission_cannot_be_replaced_by_archive_permission(app_media,monkeypatch):
    app,service,_,_=app_media
    rt=app.extensions['vwshub']
    rt.current_user=lambda:{'role':'viewer','username':'operator','permissions':{'live':False,'archive_view':True}}
    probe=Mock();monkeypatch.setattr(service,'live_audio_capabilities',probe)
    for path in ['/api/live/audio/capabilities?cam_id=ch1','/live/ch1/audio-main/index.m3u8']:
        assert app.test_client().get(path).status_code==403
    probe.assert_not_called()


def test_unknown_export_format_is_rejected_before_contacting_recorder(app_media,monkeypatch):
    app,service,_,_=app_media
    resolve=Mock();monkeypatch.setattr(service,'resolve',resolve)
    response=app.test_client().get('/api/download?cam_id=ch1&format=h265x&start=2026-10-29&end=2026-10-30')
    assert response.status_code==400 and 'H265X' in response.json['error']
    resolve.assert_not_called()


def test_concurrent_audio_requests_retain_one_stream_per_consumer(app_media,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    app,service,_,_=app_media
    barrier=threading.Barrier(2)
    def probe(*args,**kwargs):barrier.wait(timeout=3);return {'supported':True}
    monkeypatch.setattr(service,'live_audio_capabilities',probe)
    class Proc:
        code=None
        def poll(self):return self.code
        def terminate(self):self.code=-15
        def wait(self,timeout=None):return self.code
    def ensure(cam_id,stream,owner,container="ts"):
        directory=service.live.root/(cam_id+'-concurrent');directory.mkdir(exist_ok=True)
        (directory/'index.m3u8').write_text('#EXTM3U\n#EXTINF:2,\nseg_000001.ts\n')
        item={'process':Proc(),'directory':directory,'leases':{owner:time.monotonic()}}
        service.live.streams[(cam_id,stream,container)]=item
        return item
    monkeypatch.setattr(service.live,'ensure',ensure)
    def run(cam_id):return app.test_client().get('/live/'+cam_id+'/audio-main/index.m3u8?consumer='+'b'*32).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(run,['ch1','ch2']))
    assert all(code in {200,503} for code in statuses)
    assert len(service.live.streams)==1
    assert len(next(iter(service.live.streams.values()))['leases'])==1


@pytest.mark.parametrize('body',[[],{'cam_id':'ch1','stream':['audio-main']},{'cam_id':'ch1','stream':'audio-unknown'},{'cam_id':'ch1','consumer':{'nested':'bad'}}])
def test_stop_audio_rejects_malformed_payload_without_touching_streams(app_media,monkeypatch,body):
    app,service,_,_=app_media
    release=Mock();monkeypatch.setattr(service.live,'release',release)
    assert app.test_client().post('/api/live/stop',json=body).status_code==400
    release.assert_not_called()


def test_audio_playlist_rejects_unknown_profile_and_bad_consumer(app_media):
    app,_,_,_=app_media
    assert app.test_client().get('/live/ch1/audio-unknown/index.m3u8').status_code==400
    assert app.test_client().get('/live/ch1/audio-main/index.m3u8?consumer=bad').status_code==400
