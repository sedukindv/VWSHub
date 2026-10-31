"""0.8.5 invariants: catalog identity, real channel selection and scoped access."""
import copy
import io
import json
import zipfile
import io
import time
from unittest.mock import Mock

import pytest

from test_core import catalog,client,isolated_path,owner,viewer
from hub.core import create_app
from hub.store import DataStore,DataCorruptError
from hub.backup import validate_backup


@pytest.fixture
def app(isolated_path):
    return create_app(isolated_path/"data",{"TESTING":True,"REGISTER_EXTENSIONS":True,"CSRF_ENABLED":False,"LEGACY_DATA_DIR":isolated_path/"legacy"})


def account(app,owner,**policy):
    response=owner.post("/api/users",json={"username":"operator","password":"operator-test-password",**policy})
    assert response.status_code==201,response.json
    client=app.test_client()
    with client.session_transaction() as session:session["username"]="operator"
    return client


def draft(**changes):
    return {"name":"Recorder","kind":"recorder","connection":{"protocol":"dvrip","ip":"192.0.2.10","port":34567,"rtsp_port":554,"username":"operator","password":"recorder-secret"},**changes}


def probe(owner,monkeypatch,data,channels):
    monkeypatch.setattr("hub.workspace.recorder_channels",lambda *args:copy.deepcopy(channels))
    result=owner.post("/api/inventory/probe",json=data)
    assert result.status_code==200,result.json
    return result.json["probe_token"]


def test_discovery_is_read_only_and_selected_subset_is_stable(owner,catalog,monkeypatch):
    channels=[{"channel":i,"name":"Channel "+str(i+1)} for i in range(4)]
    data=draft();token=probe(owner,monkeypatch,data,channels)
    assert len(catalog.store.get_devices())==2
    saved=owner.post("/api/inventory",json={**data,"probe_token":token,"selected":[{"source_key":"dvrip:0","name":"Gate"}]})
    assert saved.status_code==201,saved.json
    parent_id=saved.json["id"];source_id=saved.json["created"][0]
    assert catalog.get_camera(source_id)["name"]=="Gate"
    assert owner.patch("/api/inventory/channels/"+source_id,json={"is_hidden":True}).status_code==200
    groups=catalog.store.get_groups();groups[0]["camera_ids"].append(source_id);catalog.store.save_groups(groups)
    second={**data,"id":parent_id};token=probe(owner,monkeypatch,second,channels[1:3])
    repeated=owner.post("/api/inventory",json={**second,"probe_token":token,"selected":[{"source_key":"dvrip:1"}]})
    assert repeated.status_code==200,repeated.json
    assert len(repeated.json["created"])==1
    source=catalog.get_camera(source_id)
    assert source["name"]=="Gate" and source["is_hidden"] and source["discovery_state"]=="missing"
    assert source_id in catalog.store.get_groups()[0]["camera_ids"]
    assert len([c for c in catalog.store.get_devices() if c["recorder_id"]==parent_id])==2


def test_probe_is_bound_to_connection_and_owner(app,owner,catalog,monkeypatch):
    data=draft();token=probe(owner,monkeypatch,data,[{"channel":0,"name":"First"}])
    altered={**data,"connection":{**data["connection"],"ip":"192.0.2.99"}}
    assert owner.post("/api/inventory",json={**altered,"probe_token":token,"selected":[{"source_key":"dvrip:0"}]}).status_code==400
    other=account(app,owner,permissions={"create_devices":True})
    assert other.post("/api/inventory",json={**data,"probe_token":token,"selected":[{"source_key":"dvrip:0"}]}).status_code==400
    assert len(catalog.store.get_devices())==2


def test_empty_physical_device_survives_channel_delete(owner,catalog):
    parent=catalog.get_camera("cam_a")["recorder_id"]
    assert owner.delete("/api/inventory/channels/cam_a",json={"confirm":True}).status_code==200
    item=next(d for d in owner.get("/api/inventory").json["devices"] if d["id"]==parent)
    assert item["channels"]==[]
    assert owner.delete("/api/inventory/"+parent,json={"confirm":True}).status_code==200
    assert not any(d["id"]==parent for d in catalog.store.get_recorders())


def test_hidden_source_is_inventory_only_and_media_is_blocked(owner,catalog):
    result=owner.patch("/api/inventory/channels/cam_a",json={"is_hidden":True})
    assert result.status_code==200
    assert "cam_a" not in {c["id"] for c in owner.get("/api/workspace").json["cameras"]}
    item=next(c for d in owner.get("/api/inventory").json["devices"] for c in d["channels"] if c["id"]=="cam_a")
    assert item["is_hidden"] and item["visibility_revision"]>0
    for path in ("/live/cam_a/main/index.m3u8","/api/cameras/cam_a/snapshot","/api/recordings?cam_id=cam_a","/api/playback?cam_id=cam_a","/api/download?cam_id=cam_a"):
        assert owner.get(path).status_code==403,path
    assert catalog.get_camera("cam_a")["id"]=="cam_a"
    assert "cam_a" in catalog.store.get_groups()[0]["camera_ids"]


def test_device_edit_does_not_grant_hardware_management(app,owner,catalog):
    parent=catalog.get_camera("cam_a")["recorder_id"]
    edit=account(app,owner,grants={"devices":{parent:"edit"}})
    assert edit.get("/api/inventory").status_code==200
    assert edit.post("/api/device/capabilities",json={"cam_id":"cam_a"}).status_code==403
    assert edit.post("/api/onvif/profiles",json={"cam_id":"cam_a"}).status_code==403
    assert edit.patch("/api/inventory/channels/cam_a",json={"name":"Allowed","is_hidden":True}).status_code==200
    assert edit.delete("/api/inventory/channels/cam_b",json={"confirm":True}).status_code==403
    assert edit.delete("/api/inventory/"+parent,json={"confirm":True}).status_code==200


def test_channel_editor_cannot_delete_parent_or_siblings(app,owner,catalog):
    parent=catalog.get_camera("cam_a")["recorder_id"]
    edit=account(app,owner,grants={"channels":{"cam_a":"edit"}})
    assert edit.delete("/api/inventory/"+parent,json={"confirm":True}).status_code==403
    assert edit.delete("/api/inventory/channels/cam_a",json={"confirm":True}).status_code==200
    assert catalog.get_camera("cam_b") is not None


def test_zone_editor_sees_only_zone_and_detaches_without_deleting(app,owner,catalog):
    zone=owner.post("/api/spaces/group_a/zones",json={"name":"Entrance","icon":"door-open","camera_ids":["cam_a"]})
    assert zone.status_code==200,zone.json
    zid=zone.json["zone_id"]
    edit=account(app,owner,grants={"zones":{zid:"edit"}})
    context=edit.get("/api/workspace").json
    assert [c["id"] for c in context["cameras"]]==["cam_a"]
    assert context["spaces"][0]["can_edit"] is False
    assert edit.patch("/api/spaces/group_a",json={"name":"No"}).status_code==403
    assert edit.patch("/api/spaces/group_a/zones/"+zid,json={"name":"Changed"}).status_code==200
    member=context["spaces"][0]["members"][0]
    assert edit.delete("/api/spaces/group_a/members/"+member["id"]).status_code==200
    assert catalog.get_camera("cam_a") is not None
    assert edit.get("/api/workspace").json["cameras"]==[]


def test_space_editor_has_no_global_source_delete(app,owner,catalog):
    edit=account(app,owner,grants={"spaces":{"group_a":"edit"}})
    assert edit.patch("/api/inventory/channels/cam_a",json={"name":"Local title"}).status_code==200
    assert edit.patch("/api/inventory/channels/cam_a",json={"is_hidden":True}).status_code==403
    assert edit.delete("/api/inventory/channels/cam_a",json={"confirm":True}).status_code==403
    assert edit.delete("/api/spaces/group_a",json={"confirm":True}).status_code==200
    assert catalog.get_camera("cam_a")
    assert next(u for u in catalog.store.get_users() if u["username"]=="operator")["grants"]["spaces"]=={}


def test_download_permission_is_separate_and_regrantable(app,owner,catalog):
    read=account(app,owner,grants={"channels":{"cam_a":"read"}},permissions={"archive_view":True})
    assert read.get("/api/download?cam_id=cam_a").status_code==403
    assert owner.put("/api/users/operator",json={"permissions":{"archive_view":True,"archive_export":True}}).status_code==200
    assert read.get("/api/download?cam_id=cam_a").status_code==400
    assert owner.put("/api/users/operator",json={"permissions":{"archive_export":False}}).status_code==200
    assert read.get("/api/download?cam_id=cam_a").status_code==403


def test_migration_is_idempotent_and_resets_only_legacy_user_export(app,owner,catalog):
    account(app,owner,grants={"spaces":{"group_a":"read"}},permissions={"archive_view":True,"archive_export":True})
    old=catalog.store.get_settings();old["schema_version"]=2;catalog.store.save_settings(old)
    ids=[c["id"] for c in catalog.store.get_devices()]
    migrated=DataStore(catalog.store.base_dir)
    assert [c["id"] for c in migrated.get_devices()]==ids
    users=migrated.get_users();operator=next(u for u in users if u["username"]=="operator")
    assert operator["permissions"]["archive_view"] and not operator["permissions"]["archive_export"]
    copies=len(list((migrated.base_dir/"migration-backups").glob("*.zip")))
    operator["permissions"]["archive_export"]=True;migrated.save_users(users)
    second=DataStore(migrated.base_dir)
    assert next(u for u in second.get_users() if u["username"]=="operator")["permissions"]["archive_export"]
    assert len(list((second.base_dir/"migration-backups").glob("*.zip")))==copies


def test_modern_backup_roundtrip_preserves_hidden_zones_and_policy(app,owner,catalog):
    owner.patch("/api/inventory/channels/cam_a",json={"is_hidden":True})
    zone=owner.post("/api/spaces/group_a/zones",json={"name":"Zone","camera_ids":["cam_a"]}).json
    account(app,owner,grants={"zones":{zone["zone_id"]:"edit"}},permissions={"archive_view":True,"archive_export":True})
    files,_=validate_backup(owner.get("/api/backup").data)
    cameras=json.loads(files["devices.json"]);spaces=json.loads(files["groups.json"]);users=json.loads(files["users.json"])
    assert next(c for c in cameras if c["id"]=="cam_a")["is_hidden"]
    assert spaces[0]["zones"][0]["id"]==zone["zone_id"]
    assert next(u for u in users if u["username"]=="operator")["permissions"]["archive_export"]


def test_admin_copy_has_no_password_or_administrator_role(owner,catalog):
    result=owner.post("/api/users/owner/clone",json={"username":"newoperator"})
    assert result.status_code==201,result.json
    user=next(u for u in catalog.store.get_users() if u["username"]=="newoperator")
    assert user["role"]=="viewer" and user["active"] is False and not user["password_hash"]
    assert owner.put("/api/users/newoperator",json={"active":True}).status_code==400
    assert owner.put("/api/users/newoperator",json={"password":"new-password-test","active":True}).status_code==200


def test_inflight_old_user_cannot_seed_new_revision_with_revoked_grants(app,owner,catalog):
    read=account(app,owner,grants={"channels":{"cam_a":"read"}})
    stale=next(u for u in catalog.store.get_users() if u["username"]=="operator")
    assert catalog.can_access_camera(stale,"cam_a")
    assert owner.put("/api/users/operator",json={"grants":{}}).status_code==200
    assert catalog.can_access_camera(stale,"cam_a") is False
    assert read.get("/api/cameras").json==[]


def test_revocation_drops_only_affected_live_lease(app,owner,catalog):
    account(app,owner,grants={"channels":{"cam_a":"read"}})
    service=app.extensions["vwshub_media"]
    directory=service.live.root/"shared-policy-test";directory.mkdir()
    process=Mock();process.poll.return_value=None
    service.live.streams[("cam_a","sub")]={"process":process,"directory":directory,"log_file":io.BytesIO(),"leases":{"owner:"+"a"*32:time.monotonic(),"operator:"+"b"*32:time.monotonic()}}
    assert owner.put("/api/users/operator",json={"grants":{}}).status_code==200
    assert set(service.live.streams[("cam_a","sub")]["leases"])=={"owner:"+"a"*32}
    process.terminate.assert_not_called()
    assert owner.patch("/api/inventory/channels/cam_a",json={"is_hidden":True}).status_code==200
    assert ("cam_a","sub") not in service.live.streams
    process.terminate.assert_called_once()


def test_revoking_download_cancels_export_without_stopping_playback(app,owner,catalog):
    account(app,owner,grants={"channels":{"cam_a":"read"}},permissions={"archive_view":True,"archive_export":True})
    service=app.extensions["vwshub_media"];export=Mock();play=Mock();other=Mock()
    base={"camera":"cam_a","auth_epoch":catalog.settings().get("auth_epoch")}
    service.operations.update({("s","download"):{**base,"username":"operator","attachment":True,"cancel":export},("s","playback"):{**base,"username":"operator","attachment":False,"cancel":play},("admin","playback"):{**base,"username":"owner","attachment":False,"cancel":other}})
    try:
        assert owner.put("/api/users/operator",json={"permissions":{"archive_export":False}}).status_code==200
        export.assert_called_once();play.assert_not_called();other.assert_not_called()
        assert owner.put("/api/users/operator",json={"grants":{}}).status_code==200
        play.assert_called_once();other.assert_not_called()
    finally:service.operations.clear()


def test_empty_device_still_requires_original_camera_key(owner,catalog):
    assert owner.delete("/api/inventory/channels/cam_a",json={"confirm":True}).status_code==200
    catalog.store.key_file.unlink()
    with pytest.raises(DataCorruptError,match="camkey"):DataStore(catalog.store.base_dir)
    assert not catalog.store.key_file.exists()


def test_future_schema_is_rejected_without_rewriting_data(owner,catalog):
    values=catalog.store.get_settings();values["schema_version"]=4;catalog.store.save_settings(values)
    before={name:(catalog.store.base_dir/name).read_bytes() for name in ("devices.json","recorders.json","groups.json","users.json","settings.json")}
    with pytest.raises(DataCorruptError,match="версия"):DataStore(catalog.store.base_dir)
    assert {name:(catalog.store.base_dir/name).read_bytes() for name in before}==before


def test_backup_with_future_schema_is_rejected(owner,catalog):
    values=catalog.store.get_settings();values["schema_version"]=4;catalog.store.save_settings(values)
    with pytest.raises(ValueError,match="версия"):validate_backup(owner.get("/api/backup").data)

def test_legacy_source_delete_prunes_direct_access_before_id_can_be_reused(app,owner,catalog):
    users=catalog.store.get_users()
    users.append({"username":"limited","role":"viewer","grants":{"channels":{"cam_a":"edit"}},"permissions":{"live":True}})
    catalog.store.save_users(users)
    assert owner.delete("/api/cameras/cam_a").status_code==200
    limited=next(u for u in catalog.store.get_users() if u["username"]=="limited")
    assert "cam_a" not in limited["grants"].get("channels",{})

def test_space_edit_switch_is_enforced_without_removing_read_access(app,owner,catalog):
    operator=account(app,owner,grants={"spaces":{"group_a":"edit"}},permissions={"edit_spaces":False})
    workspace=operator.get("/api/workspace").json
    assert workspace["spaces"][0]["can_edit"] is False
    assert operator.get("/api/cameras").json
    assert operator.patch("/api/spaces/group_a",json={"name":"Forbidden"}).status_code==403
    assert operator.post("/api/spaces",json={"name":"Forbidden"}).status_code==403
    assert operator.patch("/api/inventory/channels/cam_a",json={"name":"Forbidden"}).status_code==403


def test_space_edit_switch_preserves_read_only_scope_and_grants_own_new_space(app,owner,catalog):
    operator=account(app,owner,grants={"spaces":{"group_a":"read"}},permissions={"edit_spaces":True})
    assert operator.patch("/api/spaces/group_a",json={"name":"Forbidden"}).status_code==403
    created=operator.post("/api/spaces",json={"name":"Own space"})
    assert created.status_code==201
    identifier=created.json["space"]["id"]
    assert operator.patch("/api/spaces/"+identifier,json={"name":"Renamed own"}).status_code==200
    assert operator.patch("/api/spaces/"+identifier,json={"camera_ids":["cam_a"]}).status_code==403
    assert operator.patch("/api/inventory/channels/cam_a",json={"name":"Still read only"}).status_code==403
    assert operator.get("/api/device/cam_a/info").status_code in (403,404)

@pytest.mark.parametrize("unresolved",[False,True])
def test_space_import_cannot_self_grant_source_edit_or_deferred_access(app,owner,catalog,unresolved):
    operator=account(app,owner,grants={"spaces":{"group_a":"read"}},permissions={"edit_spaces":True})
    payload=owner.get("/api/transfers/spaces/export").json
    space=copy.deepcopy(next(s for s in payload["spaces"] if s["id"]=="group_a"))
    space["id"]="own_import";space.pop("import_id",None)
    if unresolved:
        payload["origin"]="foreign_pending"
        space["origin_id"]="foreign_pending"
        for member in space["members"]:member.update(source_id="future_source",origin_id="foreign_pending",channel_id=None)
    payload["spaces"]=[space]
    before=catalog.store.get_groups()
    result=operator.post("/api/transfers/spaces/preview",json={"payload":payload,"mode":"add"})
    assert result.status_code==403
    assert catalog.store.get_groups()==before


def test_manual_match_requires_source_edit_in_addition_to_target_space_edit(app,owner,catalog):
    created=owner.post("/api/spaces",json={"name":"Pending space"}).json["space"]
    values=catalog.store.get_groups()
    space=next(s for s in values if s["id"]==created["id"])
    space["members"]=[{"id":"pending_member","source_id":"future_source","origin_id":"foreign_pending","channel_id":None,"zone_id":None}]
    catalog.store.save_groups(values)
    operator=account(app,owner,grants={"spaces":{space["id"]:"edit","group_a":"read"}},permissions={"edit_spaces":True})
    result=operator.patch("/api/spaces/"+space["id"]+"/members/pending_member",json={"channel_id":"cam_a"})
    assert result.status_code==403
    assert next(s for s in catalog.store.get_groups() if s["id"]==space["id"])["members"][0]["channel_id"] is None
