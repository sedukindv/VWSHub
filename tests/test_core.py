"""Core regressions. Generated accounts, TEST-NET hosts and isolated data only."""
import io
import json
import sys
import uuid
import zipfile
from pathlib import Path
from unittest.mock import Mock,call

import pytest
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hub.core import create_app
from hub.store import DataStore,DataCorruptError,DEFAULT_SETTINGS

@pytest.fixture
def isolated_path():
    path=Path(__file__).resolve().parents[2]/".v7-core-tests"/uuid.uuid4().hex
    path.mkdir(parents=True)
    return path

@pytest.fixture
def app(isolated_path):
    app=create_app(isolated_path/"data",{"TESTING":True,"REGISTER_EXTENSIONS":False,"CSRF_ENABLED":False,"LEGACY_DATA_DIR":isolated_path/"legacy"})
    return app

@pytest.fixture
def client(app):return app.test_client()

@pytest.fixture
def owner(app,client):
    response=client.post("/setup",json={"username":"owner","password":"long-test-password","alias":"Operator"})
    assert response.status_code==200
    return client

@pytest.fixture
def catalog(app,owner):
    runtime=app.extensions["vwshub"]
    runtime.store.save_devices([
        {"id":"cam_a","name":"Allowed","protocol":"dvrip","ip":"192.0.2.1","port":34567,"rtsp_port":554,"username":"","password":runtime.enc_pwd("device-password"),"channel":0},
        {"id":"cam_b","name":"Hidden","protocol":"onvif","ip":"192.0.2.2","port":80,"rtsp_port":554,"username":"","password":"","rtsp_path":"/video"},
    ])
    runtime.store.save_groups([{"id":"group_a","name":"Allowed group","camera_ids":["cam_a"]},{"id":"group_b","name":"Hidden group","camera_ids":["cam_b"]}])
    return runtime

def viewer(app,owner,groups=None,archive=False):
    response=owner.post("/api/users",json={"username":"viewer","password":"viewer-test-password","role":"viewer","group_ids":groups or [],"archive_access":archive})
    assert response.status_code==201
    client=app.test_client()
    with client.session_transaction() as session:session["username"]="viewer"
    return client

def test_clean_install_has_no_default_users(client,app):
    data=client.get("/api/bootstrap").get_json()
    assert data["setup_required"] is True
    assert app.extensions["vwshub"].store.get_users()==[]
    assert client.get("/login").location.endswith("/setup")

def test_first_admin_once_only(owner,app):
    assert len(app.extensions["vwshub"].store.get_users())==1
    response=app.test_client().post("/setup",json={"username":"attacker","password":"long-password"})
    assert response.status_code==302
    assert len(app.extensions["vwshub"].store.get_users())==1

def test_setup_rejects_mismatched_confirmation_and_short_password(client):
    assert client.post("/setup",json={"username":"owner","password":"long-test-password","password_confirm":"different"}).status_code==400
    assert client.post("/setup",json={"username":"owner","password":"shortpwd"}).status_code==400

def test_setup_requires_session_csrf(isolated_path):
    app=create_app(isolated_path/"data",{"TESTING":True,"REGISTER_EXTENSIONS":False,"LEGACY_DATA_DIR":isolated_path/"legacy"})
    client=app.test_client()
    payload={"username":"owner","password":"long-test-password"}
    assert client.post("/setup",json=payload).status_code==403
    token=client.get("/api/bootstrap").get_json()["csrf_token"]
    assert client.post("/setup",json=payload,headers={"X-CSRF-Token":token}).status_code==200
    assert client.post("/api/profile",json={"alias":"New"}).status_code==403
    token=client.get("/api/bootstrap").get_json()["csrf_token"]
    assert client.post("/api/profile",json={"alias":"New"},headers={"X-CSRF-Token":token}).status_code==200

def test_legacy_migration_preserves_key_password_and_sources(isolated_path):
    legacy=isolated_path/"legacy";legacy.mkdir();key=Fernet.generate_key();fernet=Fernet(key)
    encrypted="enc:"+fernet.encrypt(b"keep-me").decode()
    (legacy/".camkey").write_bytes(key);(legacy/".flask_secret").write_text("original-session-secret")
    users=[{"username":"existing","password_hash":generate_password_hash("existing-password"),"role":"admin"}]
    devices=[{"id":"cam_a","password":encrypted,"ip":"192.0.2.1"}]
    (legacy/"users.json").write_text(json.dumps(users));(legacy/"camconfig.json").write_text(json.dumps(devices));(legacy/"groups.json").write_text("[]")
    original=(legacy/"camconfig.json").read_bytes()
    store=DataStore(isolated_path/"data",legacy)
    assert store.key_file.read_bytes()==key
    assert store.secret()=="original-session-secret"
    assert store.dec_pwd(store.get_devices()[0]["password"])=="keep-me"
    assert store.get_users()[0]["password_hash"]==users[0]["password_hash"]
    assert (legacy/"camconfig.json").read_bytes()==original
    assert not (store.base_dir/"camconfig.json").exists()

def test_missing_legacy_key_does_not_rotate_encrypted_data(isolated_path):
    legacy=isolated_path/"legacy";legacy.mkdir()
    (legacy/"camconfig.json").write_text(json.dumps([{"id":"cam_a","password":"enc:old-encrypted-password"}]))
    with pytest.raises(DataCorruptError,match="camkey"):DataStore(isolated_path/"data",legacy)
    assert not (isolated_path/"data"/".camkey").exists()

@pytest.mark.parametrize("name,expected",[("Web VMS","WVW"),("My Camera Hub","My Camera Hub")])
def test_legacy_branding_migrates_without_old_default_product_name(isolated_path,name,expected):
    legacy=isolated_path/"legacy";legacy.mkdir()
    old={"site_name":name,"tagline":"Local cameras","accent":"#abcdef","animations_enabled":False}
    source=json.dumps(old);(legacy/"branding.json").write_text(source)
    store=DataStore(isolated_path/"data",legacy)
    assert store.get_settings()["branding"]=={**DEFAULT_SETTINGS["branding"],"name":expected,"subtitle":"Local cameras","accent":"#abcdef","motion":False,"logo":"","favicon":""}
    assert (legacy/"branding.json").read_text()==source

def test_corrupt_json_is_not_silently_replaced(isolated_path):
    target=isolated_path/"data";target.mkdir();(target/"users.json").write_text("not JSON")
    with pytest.raises(DataCorruptError):DataStore(target,isolated_path/"legacy")
    assert (target/"users.json").read_text()=="not JSON"

def test_separate_store_instances_do_not_lose_concurrent_updates(isolated_path):
    from concurrent.futures import ThreadPoolExecutor
    stores=[DataStore(isolated_path/"data",isolated_path/"legacy") for _ in range(2)]
    def update(index):
        for _ in range(10):
            with stores[index].lock:
                value=stores[index].get_settings();value["test_counter"]=value.get("test_counter",0)+1;stores[index].save_settings(value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for task in [pool.submit(update,index) for index in range(2)]:task.result(timeout=10)
    assert stores[0].get_settings()["test_counter"]==20

def test_viewer_sees_only_assigned_groups_and_devices(app,owner,catalog):
    read_only=viewer(app,owner,["group_a"])
    assert [c["id"] for c in read_only.get("/api/cameras").get_json()]==["cam_a"]
    assert [g["id"] for g in read_only.get("/api/groups").get_json()]==["group_a"]
    camera=read_only.get("/api/cameras").get_json()[0]
    assert "password" not in camera
    assert camera["group_names"]==["Allowed group"]
    with app.test_request_context():
        user=catalog.store.get_users()[-1]
        assert catalog.can_access_camera(user,"cam_a") is True
        assert catalog.can_access_camera(user,"cam_b") is False
        assert catalog.can_access_archive(user) is False

def test_viewer_without_group_has_no_implicit_global_access(app,owner,catalog):
    read_only=viewer(app,owner)
    assert read_only.get("/api/cameras").get_json()==[]
    assert read_only.get("/api/groups").get_json()==[]

@pytest.mark.parametrize("path,method,payload",[("/api/users","get",None),("/api/settings","get",None),("/api/backup","get",None),("/api/logs","get",None),("/api/groups/export","get",None),("/api/cameras","post",{}),("/api/groups","post",{}),("/api/branding","post",{}),("/api/discovery","post",{})])
def test_viewer_cannot_administer(app,owner,catalog,path,method,payload):
    read_only=viewer(app,owner,["group_a"],True)
    response=getattr(read_only,method)(path,json=payload) if payload is not None else getattr(read_only,method)(path)
    assert response.status_code==403

def test_profile_cannot_escalate_permissions(app,owner,catalog):
    read_only=viewer(app,owner,["group_a"])
    response=read_only.post("/api/profile",json={"alias":"Viewer Alias","role":"admin","group_ids":["group_b"],"archive_access":True})
    assert response.status_code==200
    saved=catalog.store.get_users()[-1]
    assert saved["role"]=="viewer" and saved["group_ids"]==["group_a"] and saved["archive_access"] is False

def test_camera_creation_protocol_defaults_and_empty_username(owner,catalog):
    response=owner.post("/api/cameras",json={"name":"New","protocol":"dvrip","ip":"192.0.2.3","group_ids":["group_a"]})
    assert response.status_code==200
    camera=response.get_json()["camera"]
    assert camera["username"]=="" and camera["port"]==34567
    changed=owner.post("/api/cameras",json={"id":camera["id"],"name":"New","protocol":"onvif","ip":"192.0.2.3"}).get_json()["camera"]
    assert changed["port"]==80

def test_invalid_group_prevents_camera_persistence(owner,catalog):
    before=catalog.store.get_devices()
    response=owner.post("/api/cameras",json={"name":"No","ip":"192.0.2.3","group_ids":["missing"]})
    assert response.status_code==400
    assert catalog.store.get_devices()==before

def test_empty_password_update_and_clone_keep_encrypted_secret(owner,catalog):
    encrypted=catalog.get_camera("cam_a")["password"]
    response=owner.post("/api/cameras",json={"id":"cam_a","name":"Renamed","ip":"192.0.2.1","password":""})
    assert response.status_code==200
    assert catalog.get_camera("cam_a")["password"]==encrypted
    clone=owner.post("/api/cameras/cam_a/clone",json={"channel":1}).get_json()["camera"]
    assert clone["id"]!="cam_a" and clone["channel"]==1 and "password" not in clone
    assert catalog.get_camera(clone["id"])["password"]==encrypted
    assert clone["id"] in catalog.store.get_groups()[0]["camera_ids"]

def test_device_edit_invalidates_old_live_worker_and_archive_metadata(app,owner,catalog):
    import threading
    media=Mock();media.lock=threading.RLock();media.files={("cam_a","old"):"cached",("cam_b","keep"):"cached"};media.audio_cache={"cam_a":"old","cam_b":"keep"}
    cancel=Mock();keep=Mock();media.operations={"old":{"camera":"cam_a","cancel":cancel},"other":{"camera":"cam_b","cancel":keep}}
    app.extensions["vwshub_media"]=media
    response=owner.post("/api/cameras",json={"id":"cam_a","name":"Edited","ip":"192.0.2.3"})
    assert response.status_code==200
    assert media.live.stop.call_args_list==[call("cam_a","main"),call("cam_a","sub"),call("cam_a","audio-main"),call("cam_a","audio-sub")]
    assert media.files=={("cam_b","keep"):"cached"} and media.audio_cache=={"cam_b":"keep"}
    cancel.assert_called_once();keep.assert_not_called()

def test_legacy_group_import_requires_preview(owner,catalog):
    old=catalog.store.get_groups()
    response=owner.post("/api/groups/import",json={"groups":[{"id":"good","name":"Good","camera_ids":["cam_a"]}]})
    assert response.status_code==410 and catalog.store.get_groups()==old
    exported=json.loads(owner.get("/api/groups/export").data)
    assert exported["format"]=="vwshub.groups" and exported["version"]==1


def test_group_delete_revokes_viewer_catalog(app,owner,catalog):
    read_only=viewer(app,owner,["group_a"],True)
    assert owner.delete("/api/groups/group_a").status_code==200
    assert read_only.get("/api/cameras").get_json()==[]
    assert catalog.store.get_users()[-1]["group_ids"]==[]

def test_current_admin_cannot_remove_or_demote_itself(owner):
    assert owner.delete("/api/users/owner").status_code==400
    assert owner.put("/api/users/owner",json={"role":"viewer"}).status_code==400

def test_settings_validate_resources_and_formats(owner):
    assert owner.post("/api/settings",json={"resources":{"profile":"custom","max_live_streams":9999}}).status_code==400
    assert owner.post("/api/settings",json={"archive_format":"exe"}).status_code==400
    response=owner.post("/api/settings",json={"resources":{"profile":"maximum"},"timezone":"UTC","snapshot_format":"png"})
    assert response.status_code==200
    settings=response.get_json()["settings"]
    assert settings["resources"]["max_live_streams"]==128 and settings["timezone"]=="UTC" and settings["version"]=="0.9.0"

def test_branding_applies_publicly_but_svg_is_rejected(app,owner):
    assert owner.post("/api/branding",json={"name":"My Hub","accent":"#123abc","motion":False}).status_code==200
    assert app.test_client().get("/api/branding").get_json()["name"]=="My Hub"
    assert owner.post("/api/branding",json={"logo":"data:image/svg+xml;base64,PHN2Zy8+"}).status_code==400
    assert owner.post("/api/profile",json={"avatar":"javascript:alert(1)"}).status_code==400

def test_templates_render_bootstrap_and_login_branding(app,owner):
    response=owner.get("/")
    assert response.status_code==200 and b'id="bootstrap-data"' in response.data and b'csrf_token' in response.data
    assert b'password_hash' not in response.data
    assert owner.post("/api/branding",json={"name":"My safe hub","accent":"#123456","motion":False}).status_code==200
    response=app.test_client().get("/login")
    assert response.status_code==200 and b'My safe hub' in response.data and b'--accent:#123456' in response.data and b'data-motion="off"' in response.data

def test_backup_contains_encrypted_data_and_key_without_plain_password(owner,catalog):
    response=owner.get("/api/backup")
    assert response.status_code==200 and "attachment" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert "data/.camkey" in archive.namelist()
        assert "device-password" not in archive.read("data/devices.json").decode()

def test_public_subnet_discovery_rejected_before_network(owner,monkeypatch):
    network=Mock(side_effect=AssertionError("must not connect"));monkeypatch.setattr("hub.core.socket.create_connection",network)
    assert owner.post("/api/discovery",json={"subnet":"8.8.8.0/24"}).status_code==400
    assert owner.post("/api/discovery",json={"subnet":"192.168.0.0/16"}).status_code==400
    network.assert_not_called()

def test_manual_status_probes_only_visible_devices(app,owner,catalog,monkeypatch):
    read_only=viewer(app,owner,["group_a"])
    fake=Mock();fake.__enter__=Mock(return_value=fake);fake.__exit__=Mock(return_value=False)
    connect=Mock(return_value=fake);monkeypatch.setattr("hub.core.socket.create_connection",connect)
    response=read_only.post("/api/cameras/status",json={"camera_ids":["cam_a","cam_b"]})
    assert set(response.get_json()["status"])=={"cam_a"}
    connect.assert_called_once_with(("192.0.2.1",34567),timeout=1.5)

def test_origin_and_audit_redaction(owner,catalog):
    assert owner.post("/api/profile",json={"alias":"No"},headers={"Origin":"https://different.example"}).status_code==403
    catalog.audit("test",{"password":"no","secret":"no","url":"rtsp://user:password@192.0.2.10/video","safe":"yes"})
    entry=owner.get("/api/logs").get_json()["logs"][0]
    assert "password" not in entry["detail"] and "secret" not in entry["detail"]
    assert "user:password" not in entry["detail"]["url"]

def test_server_restart_unavailable_without_supervisor(owner):
    assert owner.post("/api/server/restart",json={"confirm":True}).status_code==501
    assert owner.post("/api/server/restart",json={}).status_code==400

def test_branding_library_icons_are_names_not_svg_and_survive_backup(app,owner):
    payload={"logo_icon":"warehouse","favicon_icon":"camera","accent":"#279b85","icon_color":"#8c6fc5"}
    response=owner.post("/api/branding",json=payload)
    assert response.status_code==200
    for key,value in payload.items():assert response.get_json()["branding"][key]==value
    for bad in ('<svg onload="alert(1)">','https://example.test/icon.svg',None,12):
        assert owner.post("/api/branding",json={"logo_icon":bad}).status_code==400
    from hub.backup import validate_backup
    files,_=validate_backup(owner.get("/api/backup").data)
    restored=json.loads(files["settings.json"])
    assert all(restored["branding"][key]==value for key,value in payload.items())
    login=app.test_client().get("/login").get_data(as_text=True)
    assert 'data-icon="warehouse"' in login
    assert 'data-favicon-icon="camera"' in login
    assert owner.post("/api/branding",json={"logo_icon":"","favicon_icon":""}).status_code==200

def test_uploaded_logo_and_favicon_survive_restart_and_backup(app,owner,isolated_path):
    import base64,struct,zlib
    def image(color):
        def chunk(kind,data):
            return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
        raw=bytes([137,80,78,71,13,10,26,10])+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(bytes([0,*color])))+chunk(b"IEND",b"")
        return "data:image/png;base64,"+base64.b64encode(raw).decode()
    assets={"logo":image((147,96,207)),"favicon":image((19,160,138)),"logo_icon":"","favicon_icon":""}
    assert owner.post("/api/branding",json=assets).status_code==200
    stored=owner.get("/api/branding").json
    assert all(stored[key].startswith("/images/") for key in ("logo","favicon"))
    for key in ("logo","favicon"):
        assert owner.get(stored[key]).data==base64.b64decode(assets[key].split(",",1)[1])
    restarted=create_app(isolated_path/"data",{"TESTING":True,"REGISTER_EXTENSIONS":False,"CSRF_ENABLED":False,"LEGACY_DATA_DIR":isolated_path/"legacy"})
    assert restarted.test_client().get("/api/branding").json==stored
    login=restarted.test_client().get("/login").get_data(as_text=True)
    assert stored["logo"] in login and stored["favicon"] in login
    from hub.backup import validate_backup
    files,_=validate_backup(owner.get("/api/backup").data)
    brand=json.loads(files["settings.json"])["branding"]
    assert all(brand[key]==stored[key] for key in assets)
    for key in ("logo","favicon"):
        assert files["images/"+brand[key].split("/")[-1]]==base64.b64decode(assets[key].split(",",1)[1])


def test_legacy_space_creation_flag_is_accepted_and_normalized(owner):
    result=owner.post("/api/users",json={"username":"legacy_editor","password":"operator-test-password","permissions":{"create_spaces":True}})
    assert result.status_code==201
    assert result.json["user"]["permissions"]["edit_spaces"] is True
    assert "create_spaces" not in result.json["user"]["permissions"]


def test_resource_manual_change_preserves_other_limits_and_becomes_custom(owner):
    assert owner.post("/api/settings",json={"resources":{"profile":"minimal"}}).status_code==200
    reply=owner.post("/api/settings",json={"resources":{"max_live_streams":7}})
    values=reply.get_json()["settings"]["resources"]
    assert values=={"profile":"custom","max_live_streams":7,"max_archive_streams":1,"archive_buffer_mb":8,"archive_idle_seconds":90,"ffmpeg_threads":1}
    result=owner.get("/api/settings").get_json()
    assert "Asia/Omsk" in result["timezones"] and len(result["timezones"])>300
    assert set(result["resource_profiles"])=={"minimal","standard","maximum"}


def test_hardware_journal_distinguishes_started_cancelled_and_failed(app):
    hardware=app.extensions["vwshub"].hardware
    for event,detail,expected in [("archive.open",{},"started"),("archive.closed",{"cancelled":True},"cancelled"),("status.unreachable",{},"failed")]:
        hardware.record(event,duration_ms=10,**detail)
        row=hardware.entries(1)[0]
        assert row["detail"]["result"]==expected
        assert row["detail"]["started_at"]<=row["time"]


def test_raster_migration_snapshot_idempotence_and_no_json_base64(app,isolated_path):
    import base64,struct,zlib
    def chunk(kind,data):
        return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    raw=b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(b"\x00\x10\x20\x30"))+chunk(b"IEND",b"")
    legacy="data:image/png;base64,"+base64.b64encode(raw).decode()
    store=app.extensions["vwshub"].store
    settings=store.get_settings();settings["branding"]["logo"]=legacy
    store._write(store.settings_file,settings)
    original=store.settings_file.read_bytes()
    restarted=create_app(isolated_path/"data",{"TESTING":True,"REGISTER_EXTENSIONS":False,"CSRF_ENABLED":False,"LEGACY_DATA_DIR":isolated_path/"legacy"})
    migrated=restarted.extensions["vwshub"].store
    url=migrated.get_settings()["branding"]["logo"]
    assert url.startswith("/images/") and restarted.test_client().get(url).data==raw
    assert b"data:image/" not in migrated.settings_file.read_bytes()
    copies=list((migrated.base_dir/"migration-backups").glob("before-images-*.zip"))
    assert len(copies)==1
    import zipfile
    with zipfile.ZipFile(copies[0]) as z:assert z.read("data/settings.json")==original
    migrated.images.migrate()
    assert len(list((migrated.base_dir/"migration-backups").glob("before-images-*.zip")))==1


def test_image_urls_cannot_reference_missing_assets_or_other_paths(app,owner):
    assert owner.post("/api/branding",json={"logo":"/images/"+"a"*64+".png"}).status_code==400
    assert owner.post("/api/branding",json={"logo":"/images/../.camkey"}).status_code==400
    assert app.test_client().get("/images/"+"a"*64+".png").status_code==401


def test_backup_images_restore_to_different_installation_and_reject_missing_file(app,owner,isolated_path):
    import base64,struct,zlib,io,zipfile
    from hub.backup import validate_backup
    from hub.store import DataStore
    def chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    raw=b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(b"\x00\x40\x50\x60"))+chunk(b"IEND",b"")
    assert owner.post("/api/branding",json={"logo":"data:image/png;base64,"+base64.b64encode(raw).decode()}).status_code==200
    backup=owner.get("/api/backup").data
    files,_=validate_backup(backup)
    target=DataStore(isolated_path/"other-installation")
    target.restore(files)
    url=target.get_settings()["branding"]["logo"]
    assert target.images.path(url.split("/")[-1]).read_bytes()==raw
    output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(backup)) as old,zipfile.ZipFile(output,"w") as new:
        for item in old.infolist():
            if not item.filename.startswith("data/images/"):new.writestr(item.filename,old.read(item))
    with pytest.raises(ValueError,match="изображение"):validate_backup(output.getvalue())


def test_image_collection_keeps_referenced_and_recent_files(app,owner):
    import os,time,hashlib
    store=app.extensions["vwshub"].store
    image=bytes([137,80,78,71,13,10,26,10])+b"synthetic-unused-signature-fixture"
    name=hashlib.sha256(image).hexdigest()+".png"
    path=store.images.path(name);path.write_bytes(image)
    store.images.collect();assert path.exists()
    os.utime(path,(time.time()-90000,time.time()-90000))
    store.images.collect();assert not path.exists()


def test_locales_theme_colors_and_personal_timezone_are_validated_and_backed_up(app,owner):
    from hub.backup import validate_backup
    colors={"light":{"text":"#102030","surface":"#ffffff","button_text":"#ffffff"},"dark":{"text":"#f0f0f0","surface":"#102030"}}
    assert owner.post("/api/branding",json={"theme_colors":colors}).status_code==200
    assert owner.post("/api/branding",json={"theme_colors":{"dark":{"text":"url(javascript:bad)"}}}).status_code==400
    assert owner.post("/api/branding",json={"theme_colors":{"light":{"button_text":"auto"}}}).status_code==400
    assert owner.post("/api/settings",json={"language":"ar"}).status_code==200
    assert owner.post("/api/profile",json={"language":"zh-TW","timezone":"Europe/Prague"}).status_code==200
    assert owner.get("/api/profile").json["timezone"]=="Europe/Prague"
    assert owner.post("/api/profile",json={"timezone":"../bad"}).status_code==400
    assert owner.post("/api/profile",json={"language":"unavailable"}).status_code==400
    metadata=owner.get("/api/settings").json["settings"]["supported_locales"]
    assert len(metadata)==28 and next(x for x in metadata if x["code"]=="ar")["direction"]=="rtl"
    files,_=validate_backup(owner.get("/api/backup").data)
    assert json.loads(files["settings.json"])["branding"]["theme_colors"]==colors
    assert json.loads(files["users.json"])[0]["timezone"]=="Europe/Prague"


def test_hevc_setting_is_admin_only_strict_persistent_and_portable(app,owner,catalog):
    from hub.backup import validate_backup
    assert owner.get("/api/bootstrap").json["public_settings"]["hevc_support"] is False
    before=catalog.store.get_devices()
    denied=viewer(app,owner,["group_a"])
    assert denied.post("/api/settings",json={"hevc_support":True}).status_code==403
    assert owner.post("/api/settings",json={"hevc_support":"true"}).status_code==400
    assert owner.post("/api/settings",json={"hevc_support":True}).status_code==200
    assert catalog.store.get_devices()==before
    restarted=create_app(catalog.store.base_dir,{"TESTING":True,"REGISTER_EXTENSIONS":False,"LEGACY_DATA_DIR":catalog.store.base_dir})
    assert restarted.extensions["vwshub"].settings()["hevc_support"] is True
    files,_=validate_backup(owner.get("/api/backup").data)
    assert json.loads(files["settings.json"])["hevc_support"] is True
    assert owner.post("/api/settings",json={"timezone":"UTC"}).status_code==200
    assert catalog.settings()["hevc_support"] is True
    assert owner.post("/api/settings",json={"hevc_support":False}).status_code==200
    assert owner.get("/api/bootstrap").json["public_settings"]["hevc_support"] is False


def test_old_settings_without_hevc_remain_disabled(app,owner):
    store=app.extensions["vwshub"].store
    settings=store.get_settings();settings.pop("hevc_support",None);store.save_settings(settings)
    assert owner.get("/api/settings").json["settings"]["hevc_support"] is False
    settings["hevc_support"]="false";store.settings_file.write_text(json.dumps(settings),encoding="utf-8")
    assert owner.get("/api/settings").status_code==503


def test_image_migration_write_failure_rolls_back_json(app,monkeypatch):
    import base64
    store=app.extensions["vwshub"].store
    settings=store.get_settings();settings["branding"]["logo"]="data:image/png;base64,"+base64.b64encode(b"\x89PNG\r\n\x1a\nsynthetic-migration-signature").decode()
    store._write(store.settings_file,settings)
    before={path:path.read_bytes() for path in (store.settings_file,store.users_file)}
    original=store._write_bytes;failed=False
    def failure(path,data):
        nonlocal failed
        if Path(path)==store.users_file and not failed:
            failed=True;raise OSError("synthetic full disk")
        return original(path,data)
    monkeypatch.setattr(store,"_write_bytes",failure)
    with pytest.raises(OSError):store.images.migrate()
    assert all(path.read_bytes()==data for path,data in before.items())
    assert not (store.base_dir/".restore-journal.json").exists()


def test_backup_refuses_unrestorable_size_instead_of_returning_a_bad_zip(owner,monkeypatch):
    import hub.backup
    monkeypatch.setattr(hub.backup,"MAX_BYTES",16)
    response=owner.get("/api/backup")
    assert response.status_code==413 and response.is_json


def test_legacy_512kb_brand_asset_survives_migration(app,isolated_path):
    import base64,random,struct,zlib
    def chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    pixels=random.Random(917).randbytes(512*256*3)
    rows=b"".join(b"\0"+pixels[y*1536:(y+1)*1536] for y in range(256))
    raw=b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",512,256,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(rows))+chunk(b"IEND",b"")
    assert 262144<len(raw)<524288
    store=app.extensions["vwshub"].store;settings=store.get_settings()
    settings["branding"]["logo"]="data:image/png;base64,"+base64.b64encode(raw).decode()
    store._write(store.settings_file,settings)
    restarted=create_app(isolated_path/"data",{"TESTING":True,"REGISTER_EXTENSIONS":False,"CSRF_ENABLED":False,"LEGACY_DATA_DIR":isolated_path/"legacy"})
    url=restarted.extensions["vwshub"].settings()["branding"]["logo"]
    assert restarted.test_client().get(url).data==raw


def test_connection_invalidation_stops_audio_and_clears_live_audio_fingerprint_cache(app):
    import threading
    from types import SimpleNamespace
    from unittest.mock import Mock
    worker=SimpleNamespace(lock=threading.RLock(),live=SimpleNamespace(stop=Mock()),files={},audio_cache={},live_audio_cache={"old-fingerprint":{"supported":True}},operations={})
    app.extensions["vwshub_media"]=worker
    app.extensions["vwshub_invalidate_camera"]("old-camera")
    assert {args.args for args in worker.live.stop.call_args_list}=={("old-camera",stream) for stream in ("main","sub","audio-main","audio-sub")}
    assert worker.live_audio_cache=={}
