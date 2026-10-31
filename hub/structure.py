"""0.8.5 catalog projections and a journaled, idempotent migration."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
import uuid
import zipfile
from datetime import datetime, timezone

from .access import normalize_user

CONNECTION_FIELDS = ("protocol", "ip", "port", "rtsp_port", "username", "password", "rtsp_host",
                     "rtsp_path", "rtsp_sub_path", "profile_token", "audio_enabled")


def physical_catalog(cameras, physical, connection_key, names=None):
    devices = copy.deepcopy(physical)
    explicit_kinds = {d["id"] for d in physical if d.get("kind")}
    by_id = {item["id"]: item for item in devices}
    by_key = {}
    for item in devices:
        by_key.setdefault(item["connection_key"], item)
    for camera in cameras:
        key = connection_key(camera)
        parent = by_id.get(camera.get("recorder_id")) or by_key.get(key)
        if parent is None:
            parent = {"id": "dev_" + uuid.uuid4().hex, "connection_key": key,
                      "name": ("Регистратор " if camera.get("protocol") == "dvrip" else "IP-камера ") + str(len(devices) + 1)}
            devices.append(parent)
            by_id[parent["id"]] = parent
            by_key.setdefault(key, parent)
        camera["recorder_id"] = parent["id"]
        camera.setdefault("is_hidden", False)
        camera.setdefault("visibility_revision", 0)
        camera.setdefault("source_key", "dvrip:" + str(camera.get("channel", 0)) if camera.get("protocol") == "dvrip"
                          else ("onvif:"+str(camera.get("source_token") or camera.get("profile_token")) if camera.get("source_token") or camera.get("profile_token")
                                else "rtsp:"+hashlib.sha256(str(camera.get("rtsp_path") or camera["id"]).encode()).hexdigest()[:32]))
        parent.setdefault("kind", "recorder" if camera.get("protocol") == "dvrip" else "camera")
        parent.setdefault("connection", {k: camera[k] for k in CONNECTION_FIELDS if k in camera})
        if (names or {}).get(key):
            parent["name"] = names[key]
    for parent in devices:
        children = [c for c in cameras if c.get("recorder_id") == parent["id"]]
        if parent["id"] not in explicit_kinds and len({c["source_key"] for c in children}) > 1:
            parent["kind"] = "recorder"
        if len(children) == 1 and parent["connection_key"] != connection_key(children[0]):
            parent["connection_key"] = connection_key(children[0])
            parent["connection"] = {k: children[0][k] for k in CONNECTION_FIELDS if k in children[0]}
    # Preserve legacy aliases as distinct IDs without treating them as new hardware sources.
    primary={}
    for camera in cameras:
        key=(camera["recorder_id"],camera["source_key"])
        if key in primary:camera["alias_of"]=primary[key]
        else:primary[key]=camera["id"];camera.pop("alias_of",None)
    # Empty physical devices deliberately remain registered.
    return cameras, devices


def normalize_spaces(spaces, cameras):
    known = {c["id"] for c in cameras}
    identities={(c.get("origin_id"),c.get("import_id",c["id"])):c["id"] for c in cameras}
    result = copy.deepcopy(spaces)
    for space in result:
        space.setdefault("icon", "folder")
        space.setdefault("zones", [])
        desired = set(space.get("camera_ids", []))
        members = space.get("members")
        if members is None:
            members = [{"channel_id": cid if cid in known else None, "source_id": cid, "zone_id": None}
                       for cid in space.get("camera_ids", [])]
        else:
            members = [m for m in members if m.get("channel_id") is None or m.get("channel_id") in desired]
            present = {m.get("channel_id") for m in members}
            members += [{"channel_id": cid, "source_id": cid, "zone_id": None}
                        for cid in space.get("camera_ids", []) if cid not in present]
        zones = {z["id"] for z in space["zones"]}
        seen = set()
        clean = []
        for member in members:
            member = dict(member)
            reference = member.get("source_id") or member.get("channel_id")
            identity=(member.get("origin_id"),reference)
            if identity in seen or (member.get("channel_id") and member["channel_id"] in {m.get("channel_id") for m in clean}):
                continue
            seen.add(identity)
            member["source_id"] = reference
            # A confirmed source ID can resolve a pending imported membership.
            if not member.get("channel_id"):
                if member.get("origin_id"):
                    member["channel_id"]=identities.get(identity)
                elif reference in known:member["channel_id"]=reference
            if member.get("channel_id") not in known:
                member["channel_id"] = None
            if member.get("zone_id") not in zones:
                member["zone_id"] = None
            member.setdefault("id", "member_" + uuid.uuid4().hex)
            clean.append(member)
        space["members"] = clean
        space["camera_ids"] = [m["channel_id"] for m in clean if m.get("channel_id")]
    return result


def initialize_catalog(store):
    settings = store.get_settings()
    if settings.get("schema_version", 0) >= 3:
        if not settings.get("catalog_origin"):
            settings["catalog_origin"]=uuid.uuid4().hex
            store.save_settings(settings)
        return
    from .store import protected
    folder = store.base_dir / "migration-backups"
    folder.mkdir(exist_ok=True)
    protected(folder, True)
    path = folder / ("before-0.8.5-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8] + ".zip")
    files = ("users.json", "devices.json", "recorders.json", "groups.json", "settings.json", ".camkey", ".flask_secret")
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.writestr("data/" + name, (store.base_dir / name).read_bytes())
    protected(path)
    cameras, devices = physical_catalog(store.get_devices(), store.get_recorders(), store.connection_key)
    settings.setdefault("catalog_origin",uuid.uuid4().hex)
    for source in cameras:source.setdefault("origin_id",settings["catalog_origin"])
    for device in devices:device.setdefault("origin_id",settings["catalog_origin"])
    spaces = normalize_spaces(store.get_groups(), cameras)
    old_users=store.get_users()
    users = [normalize_user(user, reset_export=True) for user in old_users]
    settings["schema_version"] = 3
    settings["schema_migrated_at"] = datetime.now(timezone.utc).isoformat()
    settings["migration_report"]={"from":"0.8 or earlier","to":"0.8.5","cameras":len(cameras),"devices":len(devices),"spaces":len(spaces),
                                  "users":len(users),"archive_download_reset":sum(u.get("role")!="admin" and bool(u.get("archive_access")) for u in old_users),
                                  "backup":"migration-backups/"+path.name,"timestamp":settings["schema_migrated_at"]}
    if old_users or cameras:
        logging.getLogger("vwshub.migration").warning("Before migration to 0.8.5: %s sources, %s devices, %s spaces; archive download disabled for %s ordinary archive users; backup: %s",
                                                     len(cameras),len(devices),len(spaces),settings["migration_report"]["archive_download_reset"],path)
    values = {"users.json": users, "devices.json": cameras, "recorders.json": devices,
              "groups.json": spaces, "settings.json": settings}
    store.transaction({name: json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
                       for name, value in values.items()})
