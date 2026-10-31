"""0.8 regressions: scoped edits, physical devices, portable data and rollback."""
import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_core import app, catalog, client, isolated_path, owner, viewer
from hub.backup import validate_backup
from hub.catalog import onvif_channels
from hub.diagnostics import scrub


def editor(app,owner,group="group_a"):
    result=owner.post("/api/users",json={"username":"editor","password":"editor-test-password","role":"viewer","group_ids":[group],"group_access":{group:"edit"}})
    assert result.status_code==201
    client=app.test_client()
    with client.session_transaction() as session:session["username"]="editor"
    return client


def test_editor_can_rename_and_detach_only_its_group(app,owner,catalog):
    groups=catalog.store.get_groups();groups[1]["camera_ids"].append("cam_a");catalog.store.save_groups(groups)
    edit=editor(app,owner)
    renamed=edit.patch("/api/cameras/cam_a",json={"name":"New camera name"})
    assert renamed.status_code==200 and "username" not in renamed.json["camera"]
    assert edit.patch("/api/cameras/cam_b",json={"name":"No"}).status_code==403
    assert edit.delete("/api/cameras/cam_a").status_code==403
    result=edit.post("/api/groups",json={"id":"group_a","name":"Edited group","camera_ids":[]})
    assert result.status_code==200
    assert catalog.get_camera("cam_a")["name"]=="New camera name"
    assert catalog.store.get_groups()[1]["camera_ids"]==["cam_b","cam_a"]
    assert edit.get("/api/cameras").get_json()==[]


def test_group_batch_rename_cannot_escape_membership(app,owner,catalog):
    edit=editor(app,owner)
    original=catalog.store.get_devices()
    payload={"id":"group_a","name":"Group","camera_ids":["cam_a"],"camera_names":{"cam_b":"Hidden"}}
    assert edit.post("/api/groups",json=payload).status_code==400
    assert catalog.store.get_devices()==original
    payload["camera_names"]={"cam_a":"Scoped rename"}
    assert edit.post("/api/groups",json=payload).status_code==200
    assert catalog.get_camera("cam_a")["name"]=="Scoped rename"
    assert edit.post("/api/groups",json={"id":"group_a","name":"Escalate","camera_ids":["cam_a","cam_b"]}).status_code==400
    assert edit.post("/api/groups",json={"id":"new_group","name":"Escalate","camera_ids":[]}).status_code==403
    assert edit.delete("/api/groups/group_a").status_code==403


def test_read_access_cannot_edit_and_removing_assignment_drops_edit_grant(app,owner,catalog):
    read=viewer(app,owner,["group_a"])
    assert read.patch("/api/cameras/cam_a",json={"name":"No"}).status_code==403
    edit=editor(app,owner)
    assert owner.put("/api/users/editor",json={"group_ids":[]}).status_code==200
    assert edit.patch("/api/cameras/cam_a",json={"name":"No"}).status_code==403
    assert next(u for u in catalog.store.get_users() if u["username"]=="editor")["group_access"]=={}


def test_recorder_name_is_independent_and_shared_by_channels(owner,catalog):
    before=catalog.get_camera("cam_a").copy()
    recorder=owner.get("/api/recorders").get_json()[0]
    assert owner.patch("/api/recorders/"+recorder["id"],json={"name":"Main DVR"}).status_code==200
    assert catalog.get_camera("cam_a")==before
    public=owner.get("/api/cameras").get_json()[0]
    assert public["recorder_name"]=="Main DVR" and "password" not in public


def test_legacy_recorder_add_cannot_create_channels_without_selection(owner,catalog,monkeypatch):
    probe=Mock();monkeypatch.setattr("hub.catalog.recorder_channels",probe)
    before=catalog.store.get_devices()
    response=owner.post("/api/recorders",json={"name":"Recorder","ip":"192.0.2.1"})
    assert response.status_code==410 and catalog.store.get_devices()==before
    probe.assert_not_called()


def test_onvif_channels_are_unique_sources_with_actual_rtsp_paths(catalog,monkeypatch):
    profiles=[{"token":token,"Name":name,"VideoSourceConfiguration":{"SourceToken":source},"VideoEncoderConfiguration":{"Encoding":"H264","Resolution":{"Width":width,"Height":720}}}
              for token,name,source,width in [("a_main","Entrance","source_a",1280),("a_sub","Entrance SD","source_a",320),("b_main","Yard","source_b",1280)]]
    media=SimpleNamespace(GetProfiles=lambda:profiles,GetStreamUri=lambda value:{"Uri":"rtsp://192.0.2.2:8554/"+value["ProfileToken"]})
    monkeypatch.setattr("hub.devices.connect_onvif",lambda *_:SimpleNamespace(create_media_service=lambda:media))
    channels=onvif_channels(catalog,catalog.get_camera("cam_b"))
    assert len(channels)==2 and channels[0]["rtsp_path"]=="/a_main"
    assert channels[0]["rtsp_sub_path"]=="/a_sub" and channels[0]["rtsp_port"]==8554 and channels[0]["rtsp_host"]=="192.0.2.2"


def test_status_probes_physical_dvr_once_for_many_channels(owner,catalog,monkeypatch):
    first=catalog.get_camera("cam_a")
    catalog.store.save_devices([dict(first,id=f"channel_{i}",channel=i) for i in range(24)])
    connection=Mock();connection.__enter__=Mock();connection.__exit__=Mock(return_value=False)
    probe=Mock(return_value=connection);monkeypatch.setattr("hub.catalog.socket.create_connection",probe)
    response=owner.post("/api/cameras/status",json={})
    assert len(response.json["status"])==24 and all(s["online"] for s in response.json["status"].values())
    assert probe.call_count==1


def test_status_retries_control_port_then_reports_rtsp_evidence(owner,catalog,monkeypatch):
    connection=Mock();connection.__enter__=Mock();connection.__exit__=Mock(return_value=False)
    probe=Mock(side_effect=[TimeoutError(),ConnectionRefusedError(),connection]);monkeypatch.setattr("hub.catalog.socket.create_connection",probe)
    result=owner.post("/api/cameras/status",json={"camera_ids":["cam_a"]}).json["status"]["cam_a"]
    assert result["online"] is True and result["method"]=="rtsp" and result["port"]==554
    assert [call.args[0][1] for call in probe.call_args_list]==[34567,34567,554]


def test_legacy_camera_import_requires_preview_and_export_omits_secrets(owner,catalog):
    exported=owner.get("/api/cameras/export").json
    assert exported["format"]=="vwshub.cameras" and all("password" not in c for c in exported["cameras"])
    before=catalog.store.get_devices()
    response=owner.post("/api/cameras/import",json=exported)
    assert response.status_code==410 and catalog.store.get_devices()==before


def backup_with(raw,filename,value):
    output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source,zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():target.writestr(name,json.dumps(value).encode() if name=="data/"+filename else source.read(name))
    return output.getvalue()


def test_legacy_07_backup_without_recorder_metadata_remains_restorable(owner,catalog):
    raw=owner.get("/api/backup").data;output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source,zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            if name=="data/recorders.json":continue
            content=source.read(name)
            if name=="data/settings.json":
                values=json.loads(content);values.pop("schema_version",None);values.pop("catalog_origin",None)
                content=json.dumps(values).encode()
            if name=="data/devices.json":
                values=json.loads(content)
                for value in values:value.pop("recorder_id",None)
                content=json.dumps(values).encode()
            target.writestr(name,content)
    files,summary=validate_backup(output.getvalue())
    assert summary["cameras"]==2 and summary["recorders"]==2
    assert all(c["recorder_id"] for c in json.loads(files["devices.json"]))


@pytest.mark.parametrize("filename,value",[
    ("settings.json",{"diagnostics":[]}),
    ("settings.json",{"language":[]}),
    ("settings.json",{"resources":{"profile":[]}}),
    ("devices.json",[{"id":"cam_a","name":"Bad","ip":"192.0.2.1","protocol":[]}]),
    ("groups.json",[{"id":"group_a","name":"Bad","camera_ids":["missing"]}]),
    ("users.json",[]),
])
def test_invalid_backups_are_rejected_before_any_write(owner,catalog,filename,value):
    raw=owner.get("/api/backup").data;before=catalog.store.get_devices()
    response=owner.post("/api/backup/inspect",data={"file":(io.BytesIO(backup_with(raw,filename,value)),"bad.zip")})
    assert response.status_code==400
    assert catalog.store.get_devices()==before


def test_backup_path_traversal_and_zip_duplicates_are_rejected(owner,catalog):
    raw=owner.get("/api/backup").data
    output=io.BytesIO(raw)
    with zipfile.ZipFile(output,"a") as target:target.writestr("../outside","never extract")
    with pytest.raises(ValueError):validate_backup(output.getvalue())


def test_restore_checks_fingerprint_preserves_safety_copy_and_invalidates_sessions(app,owner,catalog):
    read=viewer(app,owner,["group_a"])
    original=owner.get("/api/backup").data
    normalized,_=validate_backup(original)
    assert all(isinstance(content,bytes) for content in normalized.values())
    verified=owner.post("/api/backup/inspect",data={"file":(io.BytesIO(original),"backup.zip")})
    assert verified.status_code==200
    digest=verified.json["backup"]["sha256"]
    owner.patch("/api/cameras/cam_a",json={"name":"Changed after backup"})
    payload=lambda digest,confirmation:{"file":(io.BytesIO(original),"backup.zip"),"sha256":digest,"confirmation":confirmation}
    assert owner.post("/api/backup/restore",data=payload(digest,"no")).status_code==400
    assert owner.post("/api/backup/restore",data=payload("0"*64,"RESTORE")).status_code==400
    assert owner.post("/api/backup/restore",data=payload(digest,"RESTORE")).status_code==200
    assert catalog.get_camera("cam_a")["name"]=="Allowed" and catalog.dec_pwd(catalog.get_camera("cam_a")["password"])=="device-password"
    assert read.get("/api/cameras").status_code==401 and owner.get("/api/cameras").status_code==401
    safety=list((catalog.store.base_dir/"restore-backups").glob("*.zip"));assert len(safety)==1
    with zipfile.ZipFile(safety[0]) as archive:assert json.loads(archive.read("data/devices.json"))[0]["name"]=="Changed after backup"


def test_catalog_transaction_rolls_back_on_a_partial_disk_failure(catalog,monkeypatch):
    store=catalog.store;before={name:(store.base_dir/name).read_bytes() for name in ("devices.json","groups.json","recorders.json")}
    real=store._write_bytes;failed=False
    def fail_once(path,data):
        nonlocal failed
        if path.name=="groups.json" and not failed:failed=True;raise OSError("synthetic disk failure")
        return real(path,data)
    monkeypatch.setattr(store,"_write_bytes",fail_once)
    with pytest.raises(OSError):store.save_catalog([],[])
    assert all((store.base_dir/name).read_bytes()==raw for name,raw in before.items())
    assert not (store.base_dir/".restore-journal.json").exists()


def test_hardware_diagnostics_redacts_secrets_and_admin_can_clear(owner,catalog):
    catalog.hardware.record("test",catalog.get_camera("cam_a"),password="never",url="rtsp://user:secret@192.0.2.1/video?password=private")
    raw=owner.get("/api/hardware/logs/export").get_data(as_text=True)
    assert all(secret not in raw for secret in ("never","secret","private","device-password"))
    assert "[redacted]" in raw
    assert owner.post("/api/logs/clear",json={"kind":"hardware","confirm":True}).status_code==200
    assert owner.get("/api/hardware/logs").json["logs"]==[]
    settings=catalog.store.get_settings();settings["diagnostics"]["enabled"]=False;catalog.store.save_settings(settings)
    catalog.hardware.record("disabled",catalog.get_camera("cam_a"))
    assert catalog.hardware.entries()==[]
