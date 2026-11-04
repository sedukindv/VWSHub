"""TEST ONLY: local synthetic UI fixture. Never imported by app.py.

Explicit execution enables mock devices and test-account auto-login. No physical
hardware is contacted. Run only on loopback; default port 5091.
"""
from pathlib import Path
import tempfile,subprocess,shutil,copy
import sys,uuid,json,os
from datetime import datetime,timedelta
from flask import session,request,jsonify,send_file
from werkzeug.security import generate_password_hash

project=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(project))
from hub.core import create_app

IS_SETUP=os.environ.get("WVW_BROWSER_SETUP")=="1"
IS_HEVC=os.environ.get("WVW_BROWSER_HEVC")=="1"
data=Path(os.environ["WVW_BROWSER_DATA"]) if os.environ.get("WVW_BROWSER_DATA") else project/"tests"/".browser-data"/uuid.uuid4().hex
data.mkdir(parents=True,exist_ok=True)
ASSETS=data/"synthetic-media";ASSETS.mkdir(exist_ok=True)
ffmpeg=os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
if not ffmpeg:raise RuntimeError("Browser fixtures require FFmpeg")
subprocess.run([ffmpeg,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc=size=320x180:rate=10","-t","12","-vf","format=yuv420p","-c:v","libx264","-threads","1","-g","10",str(ASSETS/"sample.mp4")],check=True)
subprocess.run([ffmpeg,"-hide_banner","-loglevel","error","-y","-i",str(ASSETS/"sample.mp4"),"-c:v","copy","-an","-f","hls","-hls_time","1","-hls_list_size","0",str(ASSETS/"index.m3u8")],check=True)
HEVC_ASSETS=data/"synthetic-hevc"
if IS_HEVC:
 HEVC_ASSETS.mkdir(exist_ok=True)
 subprocess.run([ffmpeg,"-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=320x180:rate=10","-t","12","-c:v","libx265","-preset","ultrafast","-threads","1","-x265-params","pools=1:frame-threads=1:keyint=10:min-keyint=10:scenecut=0:log-level=error","-tag:v","hvc1",str(HEVC_ASSETS/"sample.mp4")],check=True)
 subprocess.run([ffmpeg,"-hide_banner","-loglevel","error","-y","-i",str(HEVC_ASSETS/"sample.mp4"),"-c:v","copy","-an","-f","hls","-hls_segment_type","fmp4","-hls_fmp4_init_filename","init.mp4","-hls_time","1","-hls_list_size","0",str(HEVC_ASSETS/"index.m3u8")],check=True)
 probe=subprocess.run([os.environ.get("FFPROBE_BINARY") or shutil.which("ffprobe") or "ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=codec_name,width,height","-of","json",str(HEVC_ASSETS/"sample.mp4")],check=True,capture_output=True,text=True)
 assert json.loads(probe.stdout)["streams"][0]=={"codec_name":"hevc","width":320,"height":180},probe.stdout

app=create_app(data_dir=data,config={'TESTING':True,'LEGACY_DATA_DIR':data,'SECRET_KEY':'isolated-v090-preview-key','SESSION_COOKIE_NAME':'wvw_browser_qa'})
rt=app.extensions['vwshub']
if IS_HEVC:
 settings=rt.settings();settings['hevc_support']=True;rt.store.save_settings(settings)
devices=[]
if not IS_SETUP and not rt.store.get_devices():
 rt.store.save_users([
  {'username':'demo_admin','alias':'Оператор системы','avatar':'','password_hash':generate_password_hash('synthetic-demo-password'),'role':'admin','theme':'dark','language':'ru','group_ids':[],'archive_access':True},
  {'username':'demo_viewer','alias':'Наблюдатель','avatar':'','password_hash':generate_password_hash('synthetic-viewer-password'),'role':'viewer','theme':'light','language':'ru','group_ids':['territory'],'archive_access':False},
 ])
 devices=[]
 for host,count in enumerate([24,21,9,8,12,7]):
  for channel in range(count):
   number=len(devices)
   devices.append({'id':f'demo_{number}','name':f'{["Офис","Столовая 1","Вкусная кулинария 1","Склад","Столовая 2","Периметр"][host]} · камера {channel+1:02}',
     'protocol':'dvrip','ip':f'192.0.2.{10+host}','port':34567,'rtsp_port':554,'channel':channel,'username':'','password':''})
 devices.append({'id':'demo_ip','name':'IP-камера · архив не поддерживается','protocol':'onvif','ip':'198.51.100.44','port':80,'rtsp_port':554,'username':'','password':'','rtsp_path':'/fixture'})
 rt.store.save_devices(devices)
 rt.store.save_users([*rt.store.get_users(),{'username':'demo_editor','alias':'Редактор объекта','role':'viewer','active':True,'password_hash':generate_password_hash('synthetic-editor-password'),'theme':'light','language':'ru','grants':{'devices':{rt.store.get_devices()[0]['recorder_id']:'edit'},'spaces':{'group_0':'edit'}},'permissions':{'live':True,'archive_view':True,'archive_export':False,'create_devices':True,'create_spaces':True}}])
 groups=[]
 for i in range(27):
  members=[c['id'] for n,c in enumerate(devices) if n%9==i%9]
  groups.append({'id':f'group_{i}','name':('Вкусная кулинария' if i%3==0 else 'Столовая' if i%3==1 else 'Офис')+f' {i+1}', 'camera_ids':members})
 for i,space in enumerate(groups):
  space['zones']=[{'id':f'zone_{i}_a','name':'Вход и касса','icon':'door-open'},{'id':f'zone_{i}_b','name':'Склад','icon':'warehouse'}]
  space['icon']=['store','building-2','house'][i%3]
  space['members']=[{'id':f'member_{i}_{n}','channel_id':cid,'source_id':cid,'zone_id':None if n<2 else space['zones'][n%2]['id']} for n,cid in enumerate(space['camera_ids'])]
 rt.store.save_groups(groups)
 records=rt.store.get_recorders()
 for i,recorder in enumerate(records):recorder['name']=f'Регистратор · объект {i+1}'
 rt.store.save_recorders(records)
 users=rt.store.get_users();users[0]['theme']='light';users[1].update(grants={'spaces':{'group_0':'read'},'zones':{'zone_1_a':'edit'}},permissions={'live':True,'archive_view':True,'archive_export':False})
 rt.store.save_users(users)
 for i in range(55):rt.hardware.record('status.online',devices[i],duration_ms=45+i,port_checked=34567)
import hub.catalog,hub.workspace
hub.workspace.recorder_channels=hub.catalog.recorder_channels=lambda runtime,camera:[{'channel':i,'name':f'Тестовый канал {i+1}',**({'source_token':f'source_{i}','profile_token':f'profile_{i}','rtsp_path':f'/fixture/{i}'} if camera['protocol']=='onvif' else {})} for i in range(32 if camera['protocol']=='dvrip' else 2)]

def login():
 if IS_SETUP:return
 if request.path in {"/login","/setup"}:
  session.pop("username",None);session.pop("auth_epoch",None);return
 if request.path.startswith('/__qa/editor'):session['username']='demo_editor'
 elif request.path.startswith('/__qa/viewer'):session['username']='demo_viewer'
 elif request.path.startswith('/__qa/admin'):session['username']='demo_admin'
 elif 'username' not in session:session['username']='demo_admin'
 session['auth_epoch']=rt.settings().get('auth_epoch')
app.before_request_funcs[None].insert(0,login)
@app.get('/__qa/editor')
@app.get('/__qa/viewer')
@app.get('/__qa/admin')
def qa_login():
 from flask import redirect
 return redirect('/')

def unavailable(**kwargs):return jsonify(error='Демонстрация: реальная камера не подключена'),503

archive_fixture={"mode":"normal"}

@app.route('/__qa/archive',methods=['GET','POST'])
def archive_controls():
 from hub.core import csrf_token
 modes={'normal':'Normal recordings','empty':'No recordings','error':'Recording lookup error','slow':'Slow playback','failed':'Playback error'}
 if request.method=='POST':
  mode=request.form.get('mode','normal')
  if mode not in modes:return 'Invalid fixture mode',400
  archive_fixture['mode']=mode
 options=''.join('<option value="'+key+'"'+(' selected' if archive_fixture['mode']==key else '')+'>'+label+'</option>' for key,label in modes.items())
 return '<h1>Archive test controls</h1><form method="post"><input type="hidden" name="csrf_token" value="'+csrf_token()+'"><label>Archive fixture mode<select name="mode">'+options+'</select></label><button>Apply archive fixture</button></form><a href="/">Open application</a>'
def fixture_live(cam_id,stream,filename='index.m3u8'):
 from flask import send_from_directory
 return send_from_directory(HEVC_ASSETS if IS_HEVC and cam_id!='demo_ip' else ASSETS,filename)

def fixture_video_capabilities():
 cam_id=request.args.get('cam_id');stream=request.args.get('stream','main');user=rt.current_user()
 if not user or not rt.can_access_camera(user,cam_id):return jsonify(error='Fixture access denied'),403
 if stream not in {'main','sub'}:return jsonify(error='Invalid fixture stream'),400
 if IS_HEVC and cam_id!='demo_ip':
  # Factual HEVC from the generated/probed source, deliberately missing the
  # optional RFC6381 detail. This exercises the supported software fallback
  # without replacing native browser APIs or disabling their security checks.
  return jsonify(live_video={'stream':stream,'codec':'hevc','container':'fmp4','codec_string':None,'width':320,'height':180,'framerate':10},hevc_support=True)
 return jsonify(live_video={'stream':stream,'codec':'h264','container':'mpegts','codec_string':'avc1.42c00b','width':320,'height':180,'framerate':10},hevc_support=rt.settings().get('hevc_support',False))

def recordings():
 if archive_fixture['mode']=='empty':return jsonify([])
 if archive_fixture['mode']=='error':return jsonify(error='Synthetic recording lookup failed'),503
 begin=datetime.fromisoformat(request.args['start']);end=datetime.fromisoformat(request.args['end']);span=end-begin;channel=int(rt.get_camera(request.args['cam_id']).get('channel',0));out=[]
 for i in range(12):
  first=begin+span*i/12;last=min(end,first+span*.065)
  out.append({'FileName':f'/{channel:02}/preview/{i}.h264','FilePath':f'/{channel:02}/preview/{i}.h264','BeginTime':first.strftime('%Y-%m-%d %H:%M:%S'),'EndTime':last.strftime('%Y-%m-%d %H:%M:%S'),'Channel':channel})
 return jsonify(out)
def playback():
 import time
 if archive_fixture['mode']=='failed':return jsonify(error='Synthetic playback failed'),503
 time.sleep(4 if archive_fixture['mode']=='slow' else .4)
 sample=ASSETS/"sample.mp4"
 return send_file(sample,mimetype='video/mp4',conditional=True) if sample.exists() else unavailable()
def status():return jsonify(success=True,status={d['id']:{'online':i!=5,'checked_at':datetime.now().isoformat()} for i,d in enumerate(rt.catalog_devices())},checked_at=datetime.now().isoformat())
def discovery():return jsonify(success=True,devices=[{'ip':'192.0.2.44','port':80,'rtsp_port':554,'protocol':'onvif','name':'Найденная тестовая камера','detected_by':'Synthetic fixture'}],warnings=['Демонстрация: сеть не сканировалась.'])

for rule in list(app.url_map.iter_rules()):
 if rule.rule=='/api/recordings':app.view_functions[rule.endpoint]=recordings
 elif rule.rule=='/api/live/capabilities':app.view_functions[rule.endpoint]=fixture_video_capabilities
 elif rule.rule=='/api/playback':app.view_functions[rule.endpoint]=playback
 elif rule.rule in {'/api/cameras/status','/api/inventory/status'}:app.view_functions[rule.endpoint]=status
 elif rule.rule=='/api/discovery':app.view_functions[rule.endpoint]=discovery
 elif rule.rule in {'/api/cameras/test','/api/inventory/test'}:app.view_functions[rule.endpoint]=lambda:jsonify(ok=True,success=True)
 elif rule.rule.startswith('/live/'):app.view_functions[rule.endpoint]=fixture_live
 elif rule.rule in {'/api/download','/api/archive/audio'} or 'snapshot' in rule.rule:app.view_functions[rule.endpoint]=unavailable
 elif rule.rule=='/api/archive/capabilities':app.view_functions[rule.endpoint]=lambda:jsonify(success=True,audio=False,audio_supported=False,audio_enabled=False,notes=['Тестовая запись без микрофона.'])
 elif rule.rule=='/api/live/audio/capabilities':app.view_functions[rule.endpoint]=lambda:jsonify(live_audio={'supported':False,'enabled':False,'reason':'Synthetic fixture has no microphone'})
for rule in list(app.url_map.iter_rules()):
 if rule.rule.startswith('/live/') or rule.rule in {'/api/recordings','/api/playback','/api/download','/api/archive/audio','/api/archive/capabilities'} or 'snapshot' in rule.rule:
  original=app.view_functions[rule.endpoint]
  def checked(*args,_original=original,_rule=rule.rule,**kwargs):
   cam_id=kwargs.get('cam_id') or request.args.get('cam_id');user=rt.current_user()
   if not user or not rt.can_access_camera(user,cam_id):return jsonify(error='Источник не доступен'),403
   archive=_rule.startswith('/api/archive') or _rule in {'/api/recordings','/api/playback','/api/download'}
   if archive and not rt.can_access_archive(user):return jsonify(error='Архив не разрешён'),403
   if _rule=='/api/download' and not rt.can_export_archive(user):return jsonify(error='Скачивание не разрешено'),403
   return _original(*args,**kwargs)
  app.view_functions[rule.endpoint]=checked

from hardware_fixture import install
install(app,rt)

@app.route('/__qa/report',methods=['GET','POST'])
def browser_report():
 import base64,re,json
 from hub.core import csrf_token
 folder=project/'browser-artifacts';folder.mkdir(exist_ok=True)
 status='Browser audit artifacts'
 if request.method=='POST':
  name=request.form.get('name','')
  if not re.fullmatch(r'[a-z0-9_-]{1,90}\.(?:jpg|json)',name):return 'Invalid artifact name',400
  target=folder/name
  if name.endswith('.jpg'):
   raw=base64.b64decode(request.form.get('data',''),validate=True)
   if len(raw)>6000000 or not raw.startswith(bytes([255,216,255])):return 'Invalid JPEG',400
  else:
   raw=json.dumps(json.loads(request.form.get('data','')),ensure_ascii=False,indent=2).encode()
   if len(raw)>6000000:return 'Report too large',400
  target.write_bytes(raw);status='Saved '+name
 return '<h1>'+status+'</h1><form method="post"><input type="hidden" name="csrf_token" value="'+csrf_token()+'"><label>Name<input name="name" aria-label="Artifact name"></label><label>Data<textarea name="data" aria-label="Artifact data"></textarea></label><button>Save artifact</button></form>'

import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)
if __name__=='__main__':
 cert,key=os.environ.get('WVW_BROWSER_CERT'),os.environ.get('WVW_BROWSER_KEY')
 if bool(cert)!=bool(key):raise RuntimeError('Test TLS certificate and key must be provided together')
 app.run(host='127.0.0.1',port=int(os.environ.get("WVW_BROWSER_PORT","5091")),threaded=True,debug=False,ssl_context=(cert,key) if cert else None)
