"""Validation shared by backup and portable catalog previews."""
from __future__ import annotations

import copy
import hashlib
import re

from . import access


def identifier(value):
    from .core import IDENTIFIER_RE
    if not isinstance(value,str) or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError("Некорректный идентификатор")
    return value


def grants(value):
    if not isinstance(value,dict) or set(value)-set(access.KINDS):
        raise ValueError("Некорректные области доступа")
    result={}
    for kind in access.KINDS:
        scope=value.get(kind,{})
        if not isinstance(scope,dict) or len(scope)>4096:
            raise ValueError("Некорректные назначения доступа")
        result[kind]={identifier(key):level for key,level in scope.items()}
        if any(level not in ("read","edit") for level in scope.values()):
            raise ValueError("Права: только чтение или редактирование")
    return result


def policy(user,reset_export=False):
    result=copy.deepcopy(user)
    if "grants" in result:result["grants"]=grants(result["grants"])
    if "permissions" in result:
        value=result["permissions"]
        if not isinstance(value,dict) or set(value)-set(access.FEATURES)-{"create_spaces"} or any(not isinstance(v,bool) for v in value.values()):
            raise ValueError("Некорректные разрешения пользователя")
    if not isinstance(result.get("active",True),bool):raise ValueError("Некорректная активность пользователя")
    pending=result.get("pending_grants",[])
    if not isinstance(pending,list) or len(pending)>16384:raise ValueError("Неверные отложенные права")
    for ref in pending:
        if not isinstance(ref,dict) or ref.get("kind") not in access.KINDS or ref.get("level") not in ("read","edit"):raise ValueError("Неверное отложенное право")
        identifier(ref.get("origin_id"));identifier(ref.get("source_id"))
    result=access.normalize_user(result,reset_export=reset_export)
    if result["permissions"]["archive_export"] and not result["permissions"]["archive_view"]:
        raise ValueError("Для скачивания необходим просмотр архива")
    return result


def icon(value,default="folder"):
    value=default if value is None else value
    if not isinstance(value,str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,70}",value):
        raise ValueError("Некорректное имя значка")
    return value


def spaces(values,camera_ids,modern=True):
    from .core import ids,text
    if not isinstance(values,list) or len(values)>1000:raise ValueError("Неверный список пространств")
    result=[];seen=set();zone_ids=set()
    for raw in values:
        if not isinstance(raw,dict):raise ValueError("Неверное пространство")
        sid=identifier(raw.get("id"))
        if sid in seen:raise ValueError("Повторяется пространство")
        seen.add(sid)
        item={"id":sid,"name":text(raw.get("name"),"Пространство",100,True),"icon":icon(raw.get("icon")),"zones":[],"members":[]}
        for key in ("origin_id","import_id"):
            if key in raw:item[key]=identifier(raw[key])
        zones=raw.get("zones",[])
        if not isinstance(zones,list) or len(zones)>1000:raise ValueError("Неверные зоны")
        for zone in zones:
            if not isinstance(zone,dict) or zone.get("zones"):raise ValueError("Вложенные зоны не поддерживаются")
            zid=identifier(zone.get("id"))
            if zid in zone_ids:raise ValueError("Повторяется идентификатор зоны")
            zone_ids.add(zid)
            item["zones"].append({"id":zid,"name":text(zone.get("name"),"Зона",100,True),"icon":icon(zone.get("icon"),"map-pin")})
            for key in ("origin_id","import_id"):
                if key in zone:item["zones"][-1][key]=identifier(zone[key])
        local_zones={z["id"] for z in item["zones"]}
        old_ids=ids(raw.get("camera_ids",[]))
        if set(old_ids)-set(camera_ids):raise ValueError("Пространство ссылается на отсутствующую камеру")
        members=raw.get("members") if modern else None
        if members is None:
            members=[{"id":"mem_"+hashlib.sha256((sid+":"+cid).encode()).hexdigest()[:24],"channel_id":cid,"source_id":cid,"zone_id":None} for cid in old_ids]
        if not isinstance(members,list) or len(members)>4096:raise ValueError("Неверный состав пространства")
        identities=set();member_ids=set();resolved=set()
        for member in members:
            if not isinstance(member,dict):raise ValueError("Неверная ссылка камеры")
            mid=identifier(member.get("id"));source_id=identifier(member.get("source_id",member.get("channel_id")))
            cid=member.get("channel_id");zid=member.get("zone_id")
            if cid is not None and (identifier(cid) not in camera_ids):raise ValueError("Отсутствует камера пространства")
            if zid is not None and zid not in local_zones:raise ValueError("Неизвестная зона")
            origin=member.get("origin_id")
            if origin is not None:identifier(origin)
            identity=(origin,source_id)
            if mid in member_ids or identity in identities or (cid and cid in resolved):raise ValueError("Камера повторяется в пространстве")
            member_ids.add(mid);identities.add(identity)
            if cid:resolved.add(cid)
            clean={"id":mid,"source_id":source_id,"channel_id":cid,"zone_id":zid}
            if origin:clean["origin_id"]=origin
            if member.get("name"):clean["name"]=text(member["name"],"Камера",150)
            item["members"].append(clean)
        item["camera_ids"]=[m["channel_id"] for m in item["members"] if m["channel_id"]]
        if modern and "members" in raw and set(old_ids)!=set(item["camera_ids"]):
            raise ValueError("Состав пространства не соответствует ссылкам")
        result.append(item)
    return result
