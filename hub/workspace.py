"""Physical inventory, spaces/zones and scoped editing for VWSHub 0.8.5."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import time
import uuid

from flask import Blueprint, abort, jsonify, request

from . import access
from .catalog import recorder_channels, check_status
from .core import body, ids, text, validate_device, public_device, public_user, public_settings, connection_signature
from .structure import physical_catalog, normalize_spaces, CONNECTION_FIELDS


def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex


def icon_name(value, default="layers-3"):
    if value is None:
        return default
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,70}", value):
        raise ValueError("Некорректное имя значка Lucide")
    return value


def commit_catalog(rt, cameras, devices, spaces, users=None):
    cameras, devices = physical_catalog(cameras, devices, rt.store.connection_key)
    spaces = normalize_spaces(spaces, cameras)
    values = {"devices.json": cameras, "recorders.json": devices, "groups.json": spaces}
    if users is not None:
        known={"spaces":{s["id"] for s in spaces},"zones":{z["id"] for s in spaces for z in s.get("zones",[])},
               "channels":{c["id"] for c in cameras},"devices":{d["id"] for d in devices}}
        for user in users:
            user["grants"]={kind:{key:level for key,level in scope.items() if key in known[kind]} for kind,scope in access.grants(user).items()}
        values["users.json"] = [access.normalize_user(u) for u in users]
    rt.store.transaction({name: json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
                          for name, value in values.items()})


def source_public(rt, camera, user, spaces=None):
    spaces = spaces if spaces is not None else rt.store.get_groups()
    managed = access.manages_source(user, camera)
    item = public_device(camera, connection=managed)
    index=rt.policy_index(user)
    item.update(can_edit=index["levels"].get(camera["id"]) == 2, can_manage=managed,
                archive_supported=camera.get("protocol") == "dvrip")
    parents = index["parents"]
    item["recorder_name"] = parents.get(camera.get("recorder_id"), {}).get("name", camera.get("ip", ""))
    item["device_kind"] = parents.get(camera.get("recorder_id"),{}).get("kind","recorder" if camera.get("protocol")=="dvrip" else "camera")
    memberships = index["memberships"].get(camera["id"],[])
    item["group_ids"] = [g["id"] for g in memberships]
    item["group_names"] = [g["name"] for g in memberships]
    item["has_password"] = bool(camera.get("password"))
    return item


def spaces_public(rt, user):
    cameras = {c["id"]: c for c in rt.store.get_devices()}
    result = []
    for space in rt.store.get_groups():
        scope = access.level(user, "spaces", space["id"])
        zones = [dict(z, can_edit=access.zone_level(user, space, z["id"]) == 2)
                 for z in space.get("zones", []) if access.zone_level(user, space, z["id"])]
        zone_ids = {z["id"] for z in zones}
        members = []
        for m in space.get("members", []):
            if not scope and m.get("zone_id") not in zone_ids:
                continue
            camera = cameras.get(m.get("channel_id"))
            if camera and not access.source_level(user, camera, [space]):
                continue
            member = dict(m)
            member.update(name=camera["name"] if camera else m.get("name") or m.get("source_id", ""),
                          state="resolved" if camera else "unresolved",
                          is_hidden=bool(camera and camera.get("is_hidden")))
            members.append(member)
        if not scope and not zones:
            continue
        result.append({"id": space["id"], "name": space["name"], "icon": space.get("icon", "folder"),
                       "zones": zones, "members": members, "camera_ids": [m["channel_id"] for m in members if m.get("channel_id")],
                       "can_edit": scope == 2, "access": "edit" if scope == 2 else "read"})
    return result


def inventory_public(rt, user):
    spaces = rt.store.get_groups()
    cameras = rt.store.get_devices()
    allowed={c["id"] for c in rt.catalog_devices(user)}
    result = []
    for device in rt.store.get_recorders():
        level = access.level(user, "devices", device["id"])
        channels = [c for c in cameras if c.get("recorder_id") == device["id"] and
                    (level or c["id"] in allowed)]
        if not level and not channels:
            continue
        connection = device.get("connection", {})
        item = {key: device[key] for key in ("id", "name", "kind", "connection_mode","last_discovered_at") if key in device}
        item.update(protocol=connection.get("protocol", device["connection_key"].split("|")[0]),
                    ip=connection.get("ip", device["connection_key"].split("|")[1]),
                    port=connection.get("port", int(device["connection_key"].split("|")[2])),
                    can_edit=level == 2, channels=[source_public(rt, c, user, spaces) for c in channels])
        if level == 2:
            item["connection"] = {k: v for k, v in connection.items() if k != "password"}
            item["has_password"] = bool(connection.get("password"))
        result.append(item)
    return result


def register_workspace(app, rt):
    bp = Blueprint("workspace", __name__)
    probes = {}

    def me():
        user = rt.current_user()
        if not user:
            abort(401)
        return user

    def parent(identifier, edit=False):
        item = next((d for d in rt.store.get_recorders() if d["id"] == identifier), None)
        if item is None:
            abort(404)
        if edit and access.level(me(), "devices", identifier) != 2:
            abort(403)
        return item

    def invalidate(identifiers):
        fn = app.extensions.get("vwshub_invalidate_camera")
        if fn:
            for identifier in identifiers:
                fn(identifier)

    @bp.get("/api/workspace")
    def context():
        user = me()
        spaces = spaces_public(rt, user)
        all_spaces = rt.store.get_groups()
        cameras = [source_public(rt, c, user, all_spaces) for c in rt.visible_devices(user)]
        return jsonify(user=public_user(user), cameras=cameras, spaces=spaces,
                       devices=inventory_public(rt, user) if access.editor(user) else [],
                       revision=rt.store.revision, schema_version=3,branding=rt.settings()["branding"],public_settings=public_settings(rt))

    @bp.get("/api/workspace/revision")
    def revision():
        return jsonify(revision=rt.store.revision, user=public_user(me()))

    @bp.get("/api/inventory")
    def inventory():
        if not access.editor(me()):
            abort(403)
        return jsonify(devices=inventory_public(rt, me()))

    def connection_draft(data):
        identifier = data.get("id")
        if identifier is not None:ids([identifier])
        old = parent(identifier, edit=True) if identifier else None
        if old is None and not access.features(me())["create_devices"]:
            abort(403)
        previous = {**(old or {}).get("connection", {}), "name": (old or {}).get("name", "Устройство")}
        raw = data.get("connection", {})
        if not isinstance(raw, dict):
            raise ValueError("Некорректное подключение")
        camera = validate_device({**raw, "name": data.get("name") or previous["name"]}, previous, rt)
        return old, camera

    @bp.post("/api/inventory/test")
    def test_connection():
        _,camera=connection_draft(body())
        from .media import dvr_connect,build_rtsp_live_url
        began=time.monotonic()
        try:
            if camera["protocol"]=="dvrip":
                connection=dvr_connect(camera)
                try:ok=True
                finally:connection.close()
            else:
                ffmpeg=shutil.which("ffmpeg")
                if not ffmpeg:return jsonify(ok=False,error="FFmpeg не установлен"),503
                result=subprocess.run([ffmpeg,"-hide_banner","-loglevel","error","-rtsp_transport","tcp","-i",build_rtsp_live_url(camera),"-frames:v","1","-an","-f","null","-"],capture_output=True,timeout=15)
                ok=result.returncode==0
            rt.hardware.record("connection.test",camera,success=ok,duration_ms=round((time.monotonic()-began)*1000))
            return jsonify(ok=ok,**({} if ok else {"error":"Камера не передала видеокадр"}))
        except subprocess.TimeoutExpired:
            rt.hardware.record("connection.timeout",camera,level="warning",duration_ms=round((time.monotonic()-began)*1000))
            return jsonify(ok=False,error="Устройство не ответило за отведённое время"),504
        except Exception as exc:
            rt.hardware.record("connection.failed",camera,level="warning",error_type=type(exc).__name__,duration_ms=round((time.monotonic()-began)*1000))
            return jsonify(ok=False,error="Проверьте адрес, протокол и учётные данные устройства"),502

    @bp.post("/api/inventory/probe")
    def probe():
        data = body()
        old, camera = connection_draft(data)
        try:
            channels = recorder_channels(rt, camera)
        except Exception:
            return jsonify(error="Не удалось получить каналы. Проверьте подключение и диагностику оборудования."), 502
        for channel in channels:
            channel["source_key"] = ("dvrip:" + str(channel["channel"]) if camera["protocol"] == "dvrip"
                                     else "onvif:" + str(channel.get("source_token") or channel.get("profile_token")))
        now = time.monotonic()
        for key in list(probes):
            if probes[key]["expires"] < now:
                probes.pop(key, None)
        if len(probes) >= 100:
            probes.pop(next(iter(probes)))
        token = uuid.uuid4().hex
        probes[token] = {"expires": now + 300, "owner": me()["username"], "device_id": (old or {}).get("id"),
                         "camera": camera, "channels": copy.deepcopy(channels)}
        existing = [c for c in rt.store.get_devices() if c.get("recorder_id") == (old or {}).get("id")]
        known = {c.get("source_key"): c for c in existing}
        return jsonify(probe_token=token, channels=[dict(c, existing_id=known.get(c["source_key"], {}).get("id")) for c in channels],
                       missing=[c["id"] for c in existing if c.get("source_key") not in {v["source_key"] for v in channels}])

    @bp.post("/api/inventory")
    def save_device():
        data = body()
        old, camera = connection_draft(data)
        kind = data.get("kind", (old or {}).get("kind", "recorder"))
        if kind not in ("recorder", "camera"):
            raise ValueError("Тип устройства: recorder или camera")
        if old and kind!=old.get("kind"):raise ValueError("Тип уже добавленного устройства менять нельзя")
        if old and camera["protocol"]!=old.get("connection",{}).get("protocol") and any(c.get("recorder_id")==old["id"] for c in rt.store.get_devices()):
            raise ValueError("Смена протокола существующего устройства требует отдельного подключения и выбора источников")
        mode=data.get("connection_mode",(old or {}).get("connection_mode") or ("dvrip" if camera["protocol"]=="dvrip" else "onvif"))
        if mode not in ("dvrip","onvif","rtsp") or (mode=="dvrip")!=(camera["protocol"]=="dvrip") or (mode=="rtsp" and kind!="camera"):
            raise ValueError("Неверный метод подключения для этого типа устройства")
        name = text(data.get("name"), "Название устройства", 150, True)
        probe_token = data.get("probe_token")
        discovered = None
        if probe_token:
            found = probes.get(probe_token)
            if not found or found["expires"] < time.monotonic() or found["owner"] != me()["username"] or found["device_id"] != (old or {}).get("id"):
                raise ValueError("Результат обнаружения устарел. Получите каналы заново")
            if (connection_signature({**found["camera"],"password":""}) != connection_signature({**camera,"password":""}) or
                    rt.dec_pwd(found["camera"].get("password","")) != rt.dec_pwd(camera.get("password",""))):
                raise ValueError("Подключение изменилось после проверки. Получите каналы заново")
            camera=copy.deepcopy(found["camera"])
            discovered = found["channels"]
        if not old and kind == "recorder" and discovered is None:
            raise ValueError("Сначала получите и выберите каналы регистратора")
        selections = data.get("selected", [])
        if not isinstance(selections, list) or len(selections) > 256:
            raise ValueError("Некорректный список выбранных каналов")
        if not old and kind == "camera" and discovered is None:
            source_key="dvrip:0" if camera["protocol"]=="dvrip" else "ip:0"
            discovered = [{"source_key": source_key, "channel": 0, "name": name,
                           **{k: camera[k] for k in ("rtsp_path", "rtsp_sub_path", "rtsp_host", "rtsp_port", "profile_token") if k in camera}}]
            selections = [{"source_key": source_key, "name": name}]
        lookup = {c["source_key"]: c for c in discovered or []}
        selected = []
        for selection in selections:
            if not isinstance(selection, dict) or not isinstance(selection.get("source_key"),str) or selection.get("source_key") not in lookup:
                raise ValueError("Выбран неизвестный канал. Получите каналы заново")
            if selection["source_key"] in {c["source_key"] for c in selected}:
                raise ValueError("Канал выбран повторно")
            selected.append({**lookup[selection["source_key"]], "name": text(selection.get("name") or lookup[selection["source_key"]]["name"], "Имя канала", 150, True)})
        if not old and not selected:
            raise ValueError("Выберите хотя бы один канал")
        if kind == "camera" and len(selected) > 1:
            raise ValueError("Для нескольких каналов выберите тип «Видеорегистратор»")
        with rt.store.lock:
            cameras = rt.store.get_devices()
            devices = rt.store.get_recorders()
            spaces = rt.store.get_groups()
            users = rt.store.get_users()
            identifier = old["id"] if old else uid("dev")
            target = next((d for d in devices if d["id"] == identifier), None)
            if target is None:
                target = {"id": identifier,"origin_id":rt.settings()["catalog_origin"]}
                devices.append(target)
            previous = target.get("connection", {})
            shared = {k: camera[k] for k in CONNECTION_FIELDS if k in camera}
            target.update(name=name, kind=kind, connection=shared, connection_mode=mode,connection_key=rt.store.connection_key(camera))
            changed = []
            current = [c for c in cameras if c.get("recorder_id") == identifier]
            changed_fields = {k for k in CONNECTION_FIELDS if shared.get(k) != previous.get(k)}
            for child in current:
                before = connection_signature(child)
                for key in changed_fields:
                    if key in shared:
                        child[key] = shared[key]
                    else:
                        child.pop(key, None)
                if before != connection_signature(child):
                    changed.append(child["id"])
            existing = {c.get("source_key"): c for c in current}
            created = []
            for channel in selected:
                if channel["source_key"] in existing:
                    continue
                raw = {**camera, **channel, "id": uid("cam")}
                child = validate_device({k: v for k, v in raw.items() if k != "password"}, camera, rt)
                child.update(id=raw["id"], name=channel["name"], recorder_id=identifier, source_key=channel["source_key"],
                             is_hidden=False, visibility_revision=0,origin_id=rt.settings()["catalog_origin"])
                if channel.get("source_token"):
                    child["source_token"] = channel["source_token"]
                cameras.append(child)
                created.append(child["id"])
            if len(cameras) > 4096 or len(devices) > 4096:
                raise ValueError("Достигнут предел каталога")
            if kind=="camera" and len({c["source_key"] for c in cameras if c.get("recorder_id")==identifier})>1:
                raise ValueError("У отдельной IP-камеры один источник. Измените её подключение вместо добавления ещё одного канала")
            if discovered is not None:
                target["last_discovered_at"] = int(time.time() * 1000)
                reported = set(lookup)
                for child in cameras:
                    if child.get("recorder_id") == identifier:
                        child["discovery_state"] = "reported" if child.get("source_key") in reported else "missing"
            if not old and me()["role"] != "admin":
                user = next(u for u in users if u["username"] == me()["username"])
                user["grants"]["devices"][identifier] = "edit"
            commit_catalog(rt, cameras, devices, spaces, users)
        invalidate(changed)
        if probe_token:
            probes.pop(probe_token, None)
        rt.audit("inventory.saved", {"device_id": identifier, "channels_added": created, "connection_changed": changed})
        return jsonify(success=True, id=identifier, created=created), 200 if old else 201

    @bp.patch("/api/inventory/channels/<identifier>")
    def channel_update(identifier):
        data = body()
        if set(data) - {"name", "is_hidden"}:
            raise ValueError("Здесь меняются локальное имя и видимость источника")
        with rt.store.lock:
            cameras = rt.store.get_devices()
            camera = next((c for c in cameras if c["id"] == identifier), None)
            if camera is None:
                abort(404)
            if not rt.can_edit_camera(me(), identifier):
                abort(403)
            if "name" in data:
                camera["name"] = text(data["name"], "Имя камеры", 150, True)
            if "is_hidden" in data:
                if not access.manages_source(me(), camera):
                    abort(403)
                if not isinstance(data["is_hidden"], bool):
                    raise ValueError("is_hidden: ожидается логическое значение")
                if data["is_hidden"] and not camera.get("is_hidden"):
                    camera["visibility_revision"] = int(time.time() * 1000)
                camera["is_hidden"] = data["is_hidden"]
            rt.store.save_devices(cameras)
        if data.get("is_hidden"):
            invalidate([identifier])
        rt.audit("channel.updated", {"id": identifier, "fields": list(data)})
        return jsonify(success=True)

    def remove_sources(cameras, spaces, users, selected, parent_id=None):
        selected = set(selected)
        cameras = [c for c in cameras if c["id"] not in selected]
        for space in spaces:
            space["members"] = [m for m in space.get("members", []) if m.get("channel_id") not in selected]
            space["camera_ids"] = [cid for cid in space.get("camera_ids", []) if cid not in selected]
        for user in users:
            user["grants"] = access.grants(user)
            for identifier in selected:
                user["grants"]["channels"].pop(identifier, None)
            if parent_id:
                user["grants"]["devices"].pop(parent_id, None)
        return cameras

    @bp.delete("/api/inventory/channels/<identifier>")
    def channel_delete(identifier):
        if body().get("confirm") is not True:
            raise ValueError("Подтвердите удаление источника из VWSHub")
        with rt.store.lock:
            camera = rt.get_camera(identifier)
            if camera is None:
                abort(404)
            if not access.manages_source(me(), camera):
                abort(403)
            spaces, users = rt.store.get_groups(), rt.store.get_users()
            cameras = remove_sources(rt.store.get_devices(), spaces, users, [identifier])
            commit_catalog(rt, cameras, rt.store.get_recorders(), spaces, users)
        invalidate([identifier])
        rt.audit("channel.deleted", {"id": identifier})
        return jsonify(success=True)

    @bp.delete("/api/inventory/<identifier>")
    def device_delete(identifier):
        if body().get("confirm") is not True:
            raise ValueError("Подтвердите удаление подключения и его каналов из VWSHub")
        with rt.store.lock:
            parent(identifier, edit=True)
            selected = [c["id"] for c in rt.store.get_devices() if c.get("recorder_id") == identifier]
            spaces, users = rt.store.get_groups(), rt.store.get_users()
            cameras = remove_sources(rt.store.get_devices(), spaces, users, selected, identifier)
            devices = [d for d in rt.store.get_recorders() if d["id"] != identifier]
            commit_catalog(rt, cameras, devices, spaces, users)
        invalidate(selected)
        rt.audit("inventory.deleted", {"id": identifier, "channels": selected})
        return jsonify(success=True)

    @bp.post("/api/inventory/status")
    def status():
        if not access.editor(me()):
            abort(403)
        values = rt.catalog_devices(me())
        result, stamp = check_status(rt, app, values)
        return jsonify(status=result, checked_at=stamp)

    @bp.get("/api/spaces")
    def spaces():
        return jsonify(spaces_public(rt, me()))

    def find_space(identifier):
        values = rt.store.get_groups()
        item = next((g for g in values if g["id"] == identifier), None)
        if item is None:
            abort(404)
        return values, item

    def validate_members(raw, space, target_zone=None):
        if not isinstance(raw, list) or len(raw) > 4096:
            raise ValueError("Некорректный состав")
        selected = ids(raw)
        known = {c["id"]: c for c in rt.catalog_devices(me())}
        if set(selected) - set(known):
            raise ValueError("Источник не предоставлен пользователю")
        if any(not rt.can_edit_camera(me(),cid) for cid in selected):
            abort(403)
        for member in space.get("members", []):
            if member.get("channel_id") in selected and member.get("zone_id") != target_zone:
                original_zone = member.get("zone_id")
                if access.zone_level(me(), space, original_zone) != 2:
                    abort(403)
        return selected

    @bp.post("/api/spaces")
    def space_create():
        if not access.features(me())["edit_spaces"]:
            abort(403)
        data = body()
        with rt.store.lock:
            values = rt.store.get_groups()
            if len(values) >= 1000:
                raise ValueError("Достигнут предел пространств")
            item = {"id": uid("space"), "name": text(data.get("name"), "Название пространства", 100, True),
                    "icon": icon_name(data.get("icon")), "camera_ids": [], "members": [], "zones": []}
            values.append(item)
            users = rt.store.get_users()
            if me()["role"] != "admin":
                next(u for u in users if u["username"] == me()["username"])["grants"]["spaces"][item["id"]] = "edit"
            commit_catalog(rt, rt.store.get_devices(), rt.store.get_recorders(), values, users)
        rt.audit("space.created", {"id": item["id"]})
        return jsonify(success=True, space=item), 201

    @bp.patch("/api/spaces/<identifier>")
    def space_update(identifier):
        data = body()
        with rt.store.lock:
            values, space = find_space(identifier)
            if access.level(me(), "spaces", identifier) != 2:
                abort(403)
            if set(data) - {"name", "icon", "camera_ids", "order"}:
                raise ValueError("Неизвестные параметры пространства")
            if "name" in data:
                space["name"] = text(data["name"], "Название пространства", 100, True)
            if "icon" in data:
                space["icon"] = icon_name(data["icon"])
            if "camera_ids" in data:
                selected = validate_members(data["camera_ids"], space)
                existing={m.get("channel_id"):m for m in space["members"] if m.get("channel_id")}
                remaining = [m for m in space["members"] if not m.get("channel_id") or (m.get("zone_id") and m.get("channel_id") not in selected)]
                space["members"] = [dict(existing.get(cid,{"id":uid("member"),"channel_id":cid,"source_id":cid}),zone_id=None)
                                    for cid in selected] + remaining
                space["camera_ids"] = [m["channel_id"] for m in space["members"] if m.get("channel_id")]
            if "order" in data:
                ordering = ids(data["order"])
                if set(ordering) != {z["id"] for z in space["zones"]}:
                    raise ValueError("Порядок должен содержать все зоны")
                space["zones"].sort(key=lambda z: ordering.index(z["id"]))
            rt.store.save_groups(values)
        rt.audit("space.updated", {"id": identifier, "fields": list(data)})
        return jsonify(success=True)

    @bp.delete("/api/spaces/<identifier>")
    def space_delete(identifier):
        if body().get("confirm") is not True:
            raise ValueError("Подтвердите удаление пространства")
        with rt.store.lock:
            values, space = find_space(identifier)
            if access.level(me(), "spaces", identifier) != 2:
                abort(403)
            users = rt.store.get_users()
            zones = {z["id"] for z in space.get("zones", [])}
            for user in users:
                user["grants"] = access.grants(user)
                user["grants"]["spaces"].pop(identifier, None)
                user["group_ids"] = [gid for gid in user.get("group_ids", []) if gid != identifier]
                for zid in zones:
                    user["grants"]["zones"].pop(zid, None)
            commit_catalog(rt, rt.store.get_devices(), rt.store.get_recorders(), [g for g in values if g["id"] != identifier], users)
        rt.audit("space.deleted", {"id": identifier})
        return jsonify(success=True)

    @bp.route("/api/spaces/<identifier>/zones", methods=["POST"])
    @bp.route("/api/spaces/<identifier>/zones/<zone_id>", methods=["PATCH", "DELETE"])
    def zone_manage(identifier, zone_id=None):
        data = body()
        with rt.store.lock:
            values, space = find_space(identifier)
            zone = next((z for z in space["zones"] if z["id"] == zone_id), None)
            if zone_id and zone is None:
                abort(404)
            permitted = access.zone_level(me(), space, zone_id) if zone_id else access.level(me(), "spaces", identifier)
            if permitted != 2:
                abort(403)
            users = rt.store.get_users()
            if request.method == "DELETE":
                if data.get("return_to_root") is not True:
                    raise ValueError("Подтвердите возврат камер зоны в корень пространства")
                space["zones"].remove(zone)
                for member in space["members"]:
                    if member.get("zone_id") == zone_id:
                        member["zone_id"] = None
                for user in users:
                    user["grants"] = access.grants(user)
                    user["grants"]["zones"].pop(zone_id, None)
            else:
                if set(data) - {"name", "icon", "camera_ids"}:
                    raise ValueError("Зона не может содержать вложенные зоны")
                if zone is None:
                    if len(space["zones"]) >= 1000:
                        raise ValueError("Достигнут предел зон")
                    zone = {"id": uid("zone")}
                    space["zones"].append(zone)
                    zone_id = zone["id"]
                zone["name"] = text(data.get("name", zone.get("name")), "Название зоны", 100, True)
                zone["icon"] = icon_name(data.get("icon", zone.get("icon")))
                if "camera_ids" in data:
                    selected = validate_members(data["camera_ids"], space, zone_id)
                    existing={m.get("channel_id"):m for m in space["members"] if m.get("channel_id")}
                    space["members"] = [m for m in space["members"] if not m.get("channel_id") or (m.get("zone_id") != zone_id and m.get("channel_id") not in selected)]
                    space["members"] += [dict(existing.get(cid,{"id":uid("member"),"channel_id":cid,"source_id":cid}),zone_id=zone_id) for cid in selected]
                    space["camera_ids"] = [m["channel_id"] for m in space["members"] if m.get("channel_id")]
            commit_catalog(rt, rt.store.get_devices(), rt.store.get_recorders(), values, users)
        rt.audit("zone." + ("deleted" if request.method == "DELETE" else "saved"), {"space_id": identifier, "zone_id": zone_id})
        return jsonify(success=True, zone_id=zone_id)

    @bp.delete("/api/spaces/<identifier>/members/<member_id>")
    def detach(identifier, member_id):
        with rt.store.lock:
            values, space = find_space(identifier)
            member = next((m for m in space["members"] if m["id"] == member_id), None)
            if member is None:
                abort(404)
            if access.zone_level(me(), space, member.get("zone_id")) != 2:
                abort(403)
            space["members"].remove(member)
            space["camera_ids"] = [m["channel_id"] for m in space["members"] if m.get("channel_id")]
            rt.store.save_groups(values)
        rt.audit("space.member_removed", {"space_id": identifier, "member_id": member_id})
        return jsonify(success=True)

    @bp.patch("/api/spaces/<identifier>/members/<member_id>")
    def match_member(identifier, member_id):
        data = body()
        with rt.store.lock:
            values, space = find_space(identifier)
            member = next((m for m in space["members"] if m["id"] == member_id), None)
            if member is None:
                abort(404)
            if access.zone_level(me(), space, member.get("zone_id")) != 2:
                abort(403)
            cid = ids([data.get("channel_id")])[0]
            if cid not in {c["id"] for c in rt.catalog_devices(me())}:
                abort(403)
            if not rt.can_edit_camera(me(),cid):
                abort(403)
            if any(m.get("channel_id") == cid and m["id"] != member_id for m in space["members"]):
                raise ValueError("Источник уже находится в пространстве")
            # Keep the original imported identity as a durable, confirmed binding.
            member["channel_id"]=cid
            space["camera_ids"] = [m["channel_id"] for m in space["members"] if m.get("channel_id")]
            rt.store.save_groups(values)
        rt.audit("space.member_matched", {"space_id": identifier, "member_id": member_id, "channel_id": cid})
        return jsonify(success=True)

    app.register_blueprint(bp)
