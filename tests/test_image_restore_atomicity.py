"""Legacy inline images must join the same restore journal as JSON and keys."""
import base64,io,json,struct,sys,uuid,zipfile,zlib
from pathlib import Path
import pytest
from werkzeug.security import generate_password_hash
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hub.core import create_app
from hub.store import DataStore
from hub.backup import validate_backup

FILES=("users.json","groups.json","devices.json","recorders.json","settings.json",".camkey",".flask_secret")

def image(color):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+bytes(color)))+chunk(b'IEND',b'')
    return raw,'data:image/png;base64,'+base64.b64encode(raw).decode()

def snapshot(store):
    return {name:(store.base_dir/name).read_bytes() for name in FILES}|{str(path.relative_to(store.base_dir)).replace('\\','/'):path.read_bytes() for path in store.images.directory.iterdir() if path.is_file()}

@pytest.fixture
def installation():
    root=Path(__file__).resolve().parents[2]/'.image-restore-tests'/uuid.uuid4().hex
    app=create_app(root/'target',{'TESTING':True,'CSRF_ENABLED':False,'REGISTER_EXTENSIONS':False,'LEGACY_DATA_DIR':root/'unused'})
    client=app.test_client()
    assert client.post('/setup',json={'username':'owner','password':'synthetic-original-password'}).status_code==200
    runtime=app.extensions['vwshub'];store=runtime.store
    _,original=image((10,20,30))
    assert client.post('/api/branding',json={'logo':original}).status_code==200
    source=DataStore(root/'source',root/'unused-source')
    source.save_users([{'username':'restored','role':'admin','active':True,'password_hash':generate_password_hash('synthetic-restored-password')}])
    return app,client,runtime,source

def legacy_backup(source,kind):
    raw,inline=image((110,120,130))
    if kind=='logo':
        settings=source.get_settings();settings['branding'].update(name='RESTORED',logo=inline)
        source._write(source.settings_file,settings)
    else:
        users=source.get_users();users[0]['avatar']=inline
        source._write(source.users_file,users)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:archive.writestr('data/'+name,(source.base_dir/name).read_bytes())
    return output.getvalue(),raw

@pytest.mark.parametrize('kind',['logo','avatar'])
@pytest.mark.parametrize('after_write',[False,True])
def test_failed_image_write_preserves_existing_catalog_keys_and_session(installation,monkeypatch,kind,after_write):
    app,client,runtime,source=installation;store=runtime.store
    raw,_=legacy_backup(source,kind);before=snapshot(store);secret=app.secret_key
    inspected=client.post('/api/backup/inspect',data={'file':(io.BytesIO(raw),'legacy.zip')})
    assert inspected.status_code==200
    original=store._write_bytes;failed=False
    def fail(path,data):
        nonlocal failed
        if Path(path).parent==store.images.directory and not failed:
            failed=True
            if after_write:original(path,data)
            raise OSError('synthetic image storage failure')
        return original(path,data)
    monkeypatch.setattr(store,'_write_bytes',fail)
    with pytest.raises(OSError,match='synthetic image'):
        client.post('/api/backup/restore',data={'confirmation':'RESTORE','sha256':inspected.json['backup']['sha256'],'file':(io.BytesIO(raw),'legacy.zip')})
    assert failed and snapshot(store)==before
    assert app.secret_key==secret and runtime.maintenance is False
    assert client.get('/api/bootstrap').json['user']['username']=='owner'
    assert not (store.base_dir/'.restore-journal.json').exists()

@pytest.mark.parametrize('kind',['logo','avatar'])
def test_validated_legacy_images_are_materialized_before_one_restore_commit(installation,kind):
    app,client,runtime,source=installation
    raw,pixels=legacy_backup(source,kind);files,summary=validate_backup(raw)
    assert all(b'data:image/' not in files[name] for name in ('users.json','settings.json'))
    assert pixels in [value for name,value in files.items() if name.startswith('images/')]
    result=client.post('/api/backup/restore',data={'confirmation':'RESTORE','sha256':summary['sha256'],'file':(io.BytesIO(raw),'legacy.zip')})
    assert result.status_code==200 and result.json['login_required']
    store=runtime.store
    assert store.key_file.read_bytes()==source.key_file.read_bytes()
    assert app.secret_key==source.secret()
    value=store.get_settings()['branding']['logo'] if kind=='logo' else store.get_users()[0]['avatar']
    assert value.startswith('/images/') and store.images.path(value.split('/')[-1]).read_bytes()==pixels

def test_startup_recovers_image_and_key_writes_after_process_interruption(installation,monkeypatch):
    app,client,runtime,source=installation;store=runtime.store
    raw,_=legacy_backup(source,'logo');files,_=validate_backup(raw);before=snapshot(store)
    original=store._write_bytes
    class Interrupted(BaseException):pass
    def interrupt(path,data):
        original(path,data)
        if Path(path).parent==store.images.directory:raise Interrupted()
    monkeypatch.setattr(store,'_write_bytes',interrupt)
    with pytest.raises(Interrupted):store.restore(files)
    assert (store.base_dir/'.restore-journal.json').is_file()
    restarted=DataStore(store.base_dir,store.base_dir)
    assert snapshot(restarted)==before
    assert not (store.base_dir/'.restore-journal.json').exists()
