"""Portable catalogs are previewed on the server and committed as one change."""
import copy
import json

import pytest

from test_core import app,catalog,client,isolated_path,owner,viewer
from hub.transfers import decrypt_payload


def export(owner,kind):
    result=owner.get(f"/api/transfers/{kind}/export")
    assert result.status_code==200,result.json
    return result.json


def preview(owner,kind,payload,mode="add",**extra):
    result=owner.post(f"/api/transfers/{kind}/preview",json={"payload":payload,"mode":mode,**extra})
    assert result.status_code==200,result.json
    return result.json


def apply(owner,kind,plan):
    result=owner.post(f"/api/transfers/{kind}/apply",json={"token":plan["token"]})
    assert result.status_code==200,result.json


def foreign(payload):
    payload=copy.deepcopy(payload);payload["origin"]="foreign_installation"
    for parent in payload.get("devices",[]):
        parent["origin_id"]="foreign_installation"
        for source in parent["channels"]:source["origin_id"]="foreign_installation"
    for space in payload.get("spaces",[]):
        space["origin_id"]="foreign_installation"
        for zone in space["zones"]:zone["origin_id"]="foreign_installation"
        for member in space["members"]:member["origin_id"]="foreign_installation"
    return payload


def test_preview_does_not_write_and_apply_is_revision_bound(owner,catalog):
    payload=foreign(export(owner,"devices"));before=catalog.store.get_devices()
    plan=preview(owner,"devices",payload)
    assert plan["counts"]["add"]==4
    assert catalog.store.get_devices()==before
    groups=catalog.store.get_groups();groups[0]["name"]="Changed concurrently";catalog.store.save_groups(groups)
    assert owner.post("/api/transfers/devices/apply",json={"token":plan["token"]}).status_code==409
    assert catalog.store.get_devices()==before
    apply(owner,"devices",preview(owner,"devices",payload))
    assert len(catalog.store.get_devices())==4
    assert len(catalog.store.get_groups())==2


def test_invalid_later_device_rejects_whole_preview(owner,catalog):
    payload=foreign(export(owner,"devices"));payload["devices"][1]["connection"]["port"]=70000
    before=catalog.store.get_devices()
    assert owner.post("/api/transfers/devices/preview",json={"payload":payload}).status_code==400
    assert catalog.store.get_devices()==before


def test_default_export_removes_passwords_and_secret_url_parameters(owner,catalog):
    cameras=catalog.store.get_devices();cameras[1]["rtsp_path"]="/video?token=url-secret&stream=0";catalog.store.save_devices(cameras)
    payload=export(owner,"devices");serialized=json.dumps(payload)
    assert "device-password" not in serialized and "enc:" not in serialized and "url-secret" not in serialized
    source=next(c for d in payload["devices"] for c in d["channels"] if c["id"]=="cam_b")
    assert source["connection"]["rtsp_path"]=="/video?stream=0"
    apply(owner,"devices",preview(owner,"devices",payload,"merge"))
    assert catalog.get_camera("cam_b")["rtsp_path"]=="/video?token=url-secret&stream=0"
    assert catalog.dec_pwd(catalog.get_camera("cam_a")["password"])=="device-password"


def test_protected_export_preserves_secrets_only_inside_ciphertext(owner,catalog):
    cameras=catalog.store.get_devices();cameras[1]["rtsp_path"]="/video?token=inside-secret";catalog.store.save_devices(cameras)
    response=owner.post("/api/transfers/devices/export",json={"protected":True,"passphrase":"strong-file-password"})
    assert response.status_code==200,response.json
    wire=json.dumps(response.json)
    assert "device-password" not in wire and "inside-secret" not in wire and "192.0.2.1" not in wire
    payload=decrypt_payload(response.json,"strong-file-password")
    assert next(c for d in payload["devices"] for c in d["channels"] if c["id"]=="cam_b")["connection"]["rtsp_path"]=="/video?token=inside-secret"
    assert owner.post("/api/transfers/devices/preview",json={"payload":response.json,"passphrase":"incorrect-password"}).status_code==400
    apply(owner,"devices",preview(owner,"devices",response.json,"merge",passphrase="strong-file-password"))
    assert catalog.dec_pwd(catalog.get_camera("cam_a")["password"])=="device-password"


def test_plain_device_file_cannot_smuggle_credentials(owner,catalog):
    payload=export(owner,"devices");payload["devices"][0]["connection"]["password"]="plaintext-secret"
    assert owner.post("/api/transfers/devices/preview",json={"payload":payload,"mode":"merge"}).status_code==400


def test_spaces_first_create_pending_refs_then_resolve_by_origin_and_id(owner,catalog):
    spaces=foreign(export(owner,"spaces"));devices=foreign(export(owner,"devices"))
    before=[c["id"] for c in catalog.store.get_devices()]
    plan=preview(owner,"spaces",spaces);assert plan["pending"]==2
    apply(owner,"spaces",plan)
    assert [c["id"] for c in catalog.store.get_devices()]==before
    imported=[s for s in catalog.store.get_groups() if s.get("origin_id")=="foreign_installation"]
    assert len(imported)==2 and all(not m["channel_id"] for s in imported for m in s["members"])
    apply(owner,"devices",preview(owner,"devices",devices))
    imported=[s for s in catalog.store.get_groups() if s.get("origin_id")=="foreign_installation"]
    assert all(m["channel_id"] and m["channel_id"] not in before for s in imported for m in s["members"])
    # Repeating both imports never multiplies devices, channels or spaces.
    apply(owner,"devices",preview(owner,"devices",devices,"merge"))
    apply(owner,"spaces",preview(owner,"spaces",spaces,"merge"))
    assert len(catalog.store.get_devices())==4 and len(catalog.store.get_groups())==4


def test_add_mode_adds_new_channels_without_overwriting_existing_metadata(owner,catalog):
    payload=export(owner,"devices");parent=next(d for d in payload["devices"] if d["kind"]=="recorder")
    source=copy.deepcopy(parent["channels"][0]);source.update(id="extra_channel",source_key="dvrip:1",channel=1,name="Additional channel")
    source.pop("import_id",None);parent["channels"].append(source);parent["name"]="Must not replace";parent["channels"][0]["name"]="Must not replace source"
    plan=preview(owner,"devices",payload,"add")
    assert plan["counts"]["add"]==1
    apply(owner,"devices",plan)
    assert catalog.get_camera("cam_a")["name"]=="Allowed"
    assert catalog.get_camera("extra_channel")["channel"]==1
    assert next(d for d in catalog.store.get_recorders() if d["id"]==parent["id"])["name"]!="Must not replace"


def test_users_import_cannot_set_password_or_override_administrator(owner,catalog):
    payload=export(owner,"users");payload["users"][0].update(alias="Overwrite admin",password="attacker-password",password_hash="bad",role="admin")
    payload["users"].append({"username":"imported","alias":"Imported","role":"viewer","password":"must-not-be-used","password_hash":"must-not-be-used","session":"must-not-be-used","permissions":{"archive_view":True,"archive_export":False},"grants":{}})
    plan=preview(owner,"users",payload,"merge");apply(owner,"users",plan)
    users=catalog.store.get_users();assert next(u for u in users if u["username"]=="owner")["alias"]=="Operator"
    user=next(u for u in users if u["username"]=="imported")
    assert user["active"] is False and not user["password_hash"]
    assert not any(k in user for k in ("password","session"))
    exported=json.dumps(export(owner,"users"))
    assert "password" not in exported and "session" not in exported
    # Hashless inactive accounts must remain restorable in full backups.
    from hub.backup import validate_backup
    validate_backup(owner.get("/api/backup").data)


def test_missing_user_grants_never_attach_to_same_id_from_another_installation(owner,catalog):
    payload={"format":"vwshub.users","version":1,"origin":"foreign_installation","users":[{"username":"pendinguser","role":"viewer","grants":{"channels":{"cam_a":"edit"}},"permissions":{"live":True}}]}
    apply(owner,"users",preview(owner,"users",payload))
    user=next(u for u in catalog.store.get_users() if u["username"]=="pendinguser")
    assert user["grants"]["channels"]=={} and len(user["pending_grants"])==1
    apply(owner,"devices",preview(owner,"devices",foreign(export(owner,"devices"))))
    user=next(u for u in catalog.store.get_users() if u["username"]=="pendinguser")
    assert "cam_a" not in user["grants"]["channels"] and len(user["grants"]["channels"])==1
    assert user["pending_grants"]==[]


def test_editor_cannot_import_users_or_export_protected_secrets(app,owner,catalog):
    result=owner.post("/api/users",json={"username":"editor","password":"editor-password","grants":{"channels":{"cam_a":"edit"}}})
    assert result.status_code==201
    edit=app.test_client()
    with edit.session_transaction() as session:session["username"]="editor"
    assert edit.get("/api/transfers/users/export").status_code==403
    assert edit.post("/api/transfers/devices/export",json={"protected":True,"passphrase":"strong-file-password"}).status_code==403
    payload=edit.get("/api/transfers/devices/export").json
    assert [c["id"] for d in payload["devices"] for c in d["channels"]]==["cam_a"]
    assert edit.post("/api/transfers/devices/preview",json={"payload":payload,"mode":"merge"}).status_code==403


def test_apply_rolls_back_every_catalog_on_partial_disk_failure(owner,catalog,monkeypatch):
    plan=preview(owner,"devices",foreign(export(owner,"devices")))
    store=catalog.store;before={name:(store.base_dir/name).read_bytes() for name in ("devices.json","recorders.json","groups.json","users.json")}
    original=store._write_bytes;failed=False
    def write(path,data):
        nonlocal failed
        if path.name=="recorders.json" and not failed:failed=True;raise OSError("synthetic disk failure")
        return original(path,data)
    monkeypatch.setattr(store,"_write_bytes",write)
    with pytest.raises(OSError):owner.post("/api/transfers/devices/apply",json={"token":plan["token"]})
    assert {name:(store.base_dir/name).read_bytes() for name in before}==before


def test_legacy_alias_ids_survive_modern_export_import(owner,catalog):
    camera=copy.deepcopy(catalog.get_camera("cam_a"));camera.update(id="alias_camera",name="Second view of same source")
    catalog.store.save_devices([*catalog.store.get_devices(),camera])
    assert catalog.get_camera("alias_camera")["alias_of"]=="cam_a"
    payload=export(owner,"devices")
    apply(owner,"devices",preview(owner,"devices",payload,"merge"))
    assert catalog.get_camera("cam_a")["name"]=="Allowed"
    assert catalog.get_camera("alias_camera")["name"]=="Second view of same source"
    apply(owner,"devices",preview(owner,"devices",foreign(payload)))
    imported=[c for c in catalog.store.get_devices() if c.get("origin_id")=="foreign_installation"]
    assert len(imported)==3 and len({c["id"] for c in imported})==3


def test_legacy_secret_export_is_disabled(owner,catalog):
    assert owner.get("/api/cameras/export?include_passwords=1").status_code==400
    assert "enc:" not in json.dumps(owner.get("/api/cameras/export").json)


def test_regular_user_crud_rejects_missing_resource_grants(owner,catalog):
    before=catalog.store.get_users()
    result=owner.post("/api/users",json={"username":"badgrant","password":"valid-password","grants":{"channels":{"missing_camera":"edit"}}})
    assert result.status_code==400
    assert catalog.store.get_users()==before


def test_confirmed_pending_reference_remains_matched_after_repeat_import(owner,catalog):
    payload=foreign(export(owner,"spaces"))
    apply(owner,"spaces",preview(owner,"spaces",payload))
    space=next(s for s in catalog.store.get_groups() if s.get("origin_id")=="foreign_installation")
    member=space["members"][0]
    response=owner.patch(f'/api/spaces/{space["id"]}/members/{member["id"]}',json={"channel_id":"cam_a"})
    assert response.status_code==200
    apply(owner,"spaces",preview(owner,"spaces",payload,"merge"))
    updated=next(s for s in catalog.store.get_groups() if s["id"]==space["id"])
    assert updated["members"][0]["channel_id"]=="cam_a"
