"""Scoped, previewed and atomic transfers of independent VWSHub catalogs."""
from __future__ import annotations

import base64
import copy
import json
import os
import time
from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit

from cryptography.fernet import Fernet,InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from flask import Blueprint,abort,jsonify,request

from . import access,schema
from .core import body,text,integer,validate_device,request_user_payload,public_user,validate_user_grants,LOGIN_RE
from .structure import CONNECTION_FIELDS,normalize_spaces
from .workspace import uid,commit_catalog

SECRET_KEYS={"password","passwd","pass","pwd","token","secret","auth","authorization","access_token","api_key","apikey","key"}


def safe_path(value):
    parts=urlsplit(value or "")
    query=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True) if k.casefold() not in SECRET_KEYS]
    return urlunsplit(("","",parts.path,urlencode(query),""))


def public_connection(connection):
    result={k:v for k,v in connection.items() if k in CONNECTION_FIELDS and k!="password"}
    for key in ("rtsp_path","rtsp_sub_path"):
        if key in result:result[key]=safe_path(result[key])
    return result


def preserve_secret_paths(incoming,previous):
    result=dict(incoming)
    for key in ("rtsp_path","rtsp_sub_path"):
        if key in result and previous.get(key) and safe_path(previous[key])==result[key]:result[key]=previous[key]
    return result


def identity(item,default_origin):
    return (item.get("origin_id") or default_origin,item.get("import_id") or item["id"])


def object_maps(cameras,devices,spaces,origin):
    values={"channels":cameras,"devices":devices,"spaces":spaces,"zones":[z for s in spaces for z in s.get("zones",[])]}
    return {kind:{identity(item,origin):item["id"] for item in items} for kind,items in values.items()}


def resolve_pending(users,cameras,devices,spaces,origin):
    maps=object_maps(cameras,devices,spaces,origin)
    for user in users:
        remaining=[]
        for ref in user.get("pending_grants",[]):
            identifier=maps.get(ref["kind"],{}).get((ref["origin_id"],ref["source_id"]))
            if identifier:
                current=user["grants"][ref["kind"]].get(identifier)
                user["grants"][ref["kind"]][identifier]="edit" if "edit" in (current,ref["level"]) else "read"
            else:remaining.append(ref)
        user["pending_grants"]=remaining
        user.update(access.normalize_user(user))


def crypt_key(passphrase,salt):
    if not isinstance(passphrase,str) or not 12<=len(passphrase)<=256:
        raise ValueError("Пароль защищённого экспорта: от 12 до 256 символов")
    key=Scrypt(salt=salt,length=32,n=16384,r=8,p=1).derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


def encrypt_payload(payload,passphrase):
    salt=os.urandom(16)
    token=Fernet(crypt_key(passphrase,salt)).encrypt(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode())
    return {"format":"vwshub.devices.protected","version":1,"kdf":"scrypt-16384-8-1",
            "salt":base64.b64encode(salt).decode(),"ciphertext":token.decode()}


def decrypt_payload(payload,passphrase):
    if type(payload.get("version")) is not int or payload.get("version")!=1 or payload.get("kdf")!="scrypt-16384-8-1":raise ValueError("Неизвестная версия защищённого файла")
    try:
        salt=base64.b64decode(payload.get("salt",""),validate=True)
        if len(salt)!=16:raise ValueError()
        raw=Fernet(crypt_key(passphrase,salt)).decrypt(str(payload.get("ciphertext","")).encode())
        return json.loads(raw.decode())
    except (InvalidToken,UnicodeError,TypeError,ValueError):raise ValueError("Не удалось открыть защищённый файл. Проверьте пароль и целостность файла") from None


def register_transfers(app,rt):
    bp=Blueprint("transfers",__name__);plans={}

    def require(kind):
        user=rt.current_user()
        if not user:abort(401)
        if kind=="users" and user["role"]!="admin":abort(403)
        if kind!="users" and not access.editor(user):abort(403)
        return user

    def transfer_id(kind,value):
        if kind!="users":return schema.identifier(value)
        if not isinstance(value,str) or not LOGIN_RE.fullmatch(value):raise ValueError("Некорректный логин")
        return value

    def snapshot():
        return (rt.store.get_devices(),rt.store.get_recorders(),rt.store.get_groups(),rt.store.get_users())

    def export_data(kind,selected=None,secrets=False):
        user=require(kind);origin=rt.settings()["catalog_origin"]
        cameras,devices,spaces,users=snapshot()
        if selected is not None:
            if not isinstance(selected,list) or len(selected)>4096:raise ValueError("Неверный выбор объектов")
            selected={transfer_id(kind,i) for i in selected}
        payload={"format":"vwshub."+kind,"version":1,"origin":origin}
        if kind=="devices":
            allowed={c["id"] for c in rt.catalog_devices(user)};items=[]
            for device in devices:
                if selected is not None and device["id"] not in selected:continue
                managed=access.level(user,"devices",device["id"])==2
                children=[c for c in cameras if c.get("recorder_id")==device["id"] and c["id"] in allowed]
                if not managed and not children:continue
                item={k:copy.deepcopy(device[k]) for k in ("id","name","kind","connection_mode","origin_id","import_id") if k in device}
                item["connection"]={k:v for k,v in device.get("connection",{}).items() if k in CONNECTION_FIELDS and k!="password"} if secrets else public_connection(device.get("connection",{}))
                if not managed:item["connection"].pop("username",None)
                if secrets:item["connection"]["password"]=rt.dec_pwd(device.get("connection",{}).get("password",""))
                item["channels"]=[]
                for child in children:
                    entry={k:child[k] for k in ("id","name","source_key","source_token","channel","is_hidden","visibility_revision","origin_id","import_id","alias_of") if k in child}
                    entry["connection"]={k:v for k,v in child.items() if k in CONNECTION_FIELDS and k!="password"} if secrets else public_connection(child)
                    if not access.manages_source(user,child):entry["connection"].pop("username",None)
                    if secrets:entry["connection"]["password"]=rt.dec_pwd(child.get("password",""))
                    item["channels"].append(entry)
                items.append(item)
            payload["devices"]=items;payload["secrets_omitted"]=not secrets
        elif kind=="spaces":
            from .workspace import spaces_public
            allowed={s["id"] for s in spaces_public(rt,user)};by_id={c["id"]:c for c in cameras};items=[]
            for space in spaces:
                if space["id"] not in allowed or (selected is not None and space["id"] not in selected):continue
                item={k:copy.deepcopy(space[k]) for k in ("id","name","icon","origin_id","import_id") if k in space}
                item["zones"]=[copy.deepcopy(z) for z in space.get("zones",[]) if access.zone_level(user,space,z["id"])]
                item["members"]=[]
                for member in space.get("members",[]):
                    if not access.zone_level(user,space,member.get("zone_id")):continue
                    ref={k:member[k] for k in ("id","source_id","origin_id","zone_id","name") if k in member}
                    source=by_id.get(member.get("channel_id"))
                    if source:ref.update(source_id=identity(source,origin)[1],origin_id=identity(source,origin)[0],name=source["name"])
                    item["members"].append(ref)
                items.append(item)
            payload["spaces"]=items
        else:
            maps=object_maps(cameras,devices,spaces,origin)
            reverse={kind:{identifier:{"origin_id":key[0],"source_id":key[1]} for key,identifier in values.items()} for kind,values in maps.items()}
            items=[]
            for user in users:
                if selected is not None and user["username"] not in selected:continue
                item={k:copy.deepcopy(user[k]) for k in ("username","alias","avatar","theme","language","role") if k in user}
                item.update(grants=access.grants(user),permissions=access.features(user))
                item["references"]={kind:{key:reverse[kind][key] for key in item["grants"][kind] if key in reverse[kind]} for kind in access.KINDS}
                item["pending_grants"]=copy.deepcopy(user.get("pending_grants",[]));items.append(item)
            payload["users"]=items
        return payload

    @bp.route("/api/transfers/<kind>/export",methods=["GET","POST"])
    def export(kind):
        if kind not in ("devices","spaces","users"):abort(404)
        data=body() if request.method=="POST" else {}
        protected=data.get("protected") is True
        if protected and (kind!="devices" or require(kind)["role"]!="admin"):abort(403)
        payload=export_data(kind,data.get("ids"),protected)
        if protected:payload=encrypt_payload(payload,data.get("passphrase"))
        return jsonify(payload)

    def prepare_devices(payload,mode,skip,cameras,devices,spaces,users,rows,user,protected):
        origin=payload["origin"];local=rt.settings()["catalog_origin"]
        incoming=payload.get("devices")
        if not isinstance(incoming,list) or len(incoming)>4096:raise ValueError("Неверный список устройств")
        seen=set();seen_sources=set()
        for raw in incoming:
            if not isinstance(raw,dict):raise ValueError("Неверное устройство")
            source_id=schema.identifier(raw.get("id"));ident=identity(raw,origin)
            schema.identifier(ident[0]);schema.identifier(ident[1])
            if ident in seen:raise ValueError("Устройство повторяется в файле")
            seen.add(ident)
            old=next((d for d in devices if identity(d,local)==ident),None)
            if source_id in skip or (not old and mode=="update"):
                rows.append({"name":raw.get("name",source_id),"action":"skip","kind":"device"});continue
            if old and access.level(user,"devices",old["id"])!=2:abort(403)
            if not old and not access.features(user)["create_devices"]:abort(403)
            kind=raw.get("kind")
            if kind not in ("camera","recorder"):raise ValueError("Неверный тип устройства")
            if old and mode=="add":kind=old["kind"]
            connection=raw.get("connection")
            if not isinstance(connection,dict) or set(connection)-set(CONNECTION_FIELDS):raise ValueError("Неверное подключение")
            if "password" in connection and not protected:raise ValueError("Учётные данные принимаются только из защищённого экспорта устройств")
            identifier=old["id"] if old else (source_id if not any(d["id"]==source_id for d in devices) else uid("dev"))
            previous=(old or {}).get("connection",{})
            connection=preserve_secret_paths(connection,previous)
            if old and mode=="add":connection={k:v for k,v in previous.items() if k!="password"}
            draft=validate_device({**connection,"id":identifier,"name":raw.get("name")},previous,rt)
            shared={k:draft[k] for k in CONNECTION_FIELDS if k in draft}
            target=old or {"id":identifier}
            if not old or mode!="add":target.update(name=draft["name"],kind=kind,connection=shared,connection_key=rt.store.connection_key(draft),origin_id=ident[0],import_id=ident[1])
            if raw.get("connection_mode") and (not old or mode!="add"):
                if raw["connection_mode"] not in ("dvrip","onvif","rtsp"):raise ValueError("Неверный метод подключения")
                target["connection_mode"]=raw["connection_mode"]
            children=raw.get("channels",[])
            if not isinstance(children,list) or len(children)>4096:raise ValueError("Неверный список каналов")
            if not old:
                devices.append(target)
                if user["role"]!="admin":next(u for u in users if u["username"]==user["username"])["grants"]["devices"][identifier]="edit"
            rows.append({"name":target["name"],"action":("skip" if mode=="add" else "update") if old else "add","kind":"device","needs_credentials":not shared.get("password")})
            parent_sources={}
            for child in children:
                if not isinstance(child,dict):raise ValueError("Неверный канал")
                cid=schema.identifier(child.get("id"));child_ident=identity(child,origin)
                schema.identifier(child_ident[0]);schema.identifier(child_ident[1])
                source_key=text(child.get("source_key"),"Источник канала",600,True)
                if child.get("alias_of"):schema.identifier(child["alias_of"])
                if child_ident in seen_sources or (source_key in parent_sources and parent_sources[source_key] and not child.get("alias_of")):raise ValueError("Канал повторяется в файле")
                seen_sources.add(child_ident);parent_sources[source_key]=parent_sources.get(source_key,False) or not child.get("alias_of")
                old_child=next((c for c in cameras if identity(c,local)==child_ident),None)
                if old_child and old_child.get("recorder_id")!=identifier:raise ValueError("Источник уже принадлежит другому устройству")
                if not old_child and not child.get("alias_of"):old_child=next((c for c in cameras if c.get("recorder_id")==identifier and c.get("source_key")==source_key and not c.get("alias_of")),None)
                if (old_child and mode=="add") or (not old_child and mode=="update"):continue
                fields=child.get("connection",{})
                if not isinstance(fields,dict) or set(fields)-set(CONNECTION_FIELDS):raise ValueError("Неверное подключение канала")
                if "password" in fields and not protected:raise ValueError("Незащищённый файл содержит пароль канала")
                child_id=old_child["id"] if old_child else (cid if not any(c["id"]==cid for c in cameras) else uid("cam"))
                data={**connection,**fields,"id":child_id,"name":child.get("name"),"channel":child.get("channel",0)}
                previous=old_child or {**draft,"id":child_id}
                data=preserve_secret_paths(data,previous)
                if old and mode=="add":
                    for key in ("protocol","ip","port","rtsp_port","username","password","rtsp_host"):
                        data.pop(key,None)
                        if key in draft and key!="password":data[key]=draft[key]
                cleaned=validate_device(data,previous,rt)
                hidden=(old_child or child).get("is_hidden",False)
                if not isinstance(hidden,bool):raise ValueError("Неверная видимость канала")
                cleaned.update(id=child_id,recorder_id=identifier,source_key=source_key,is_hidden=hidden,
                               visibility_revision=(old_child or {}).get("visibility_revision",integer(child.get("visibility_revision",0),"Ревизия видимости",0,10**16)),origin_id=child_ident[0],import_id=child_ident[1])
                if hidden and not cleaned["visibility_revision"]:cleaned["visibility_revision"]=int(time.time()*1000)
                if child.get("alias_of"):cleaned["alias_of"]=child["alias_of"]
                if child.get("source_token"):cleaned["source_token"]=text(child["source_token"],"Источник ONVIF",600,True)
                if old_child:cameras[cameras.index(old_child)]=cleaned
                else:cameras.append(cleaned)
                rows.append({"name":cleaned["name"],"action":"update" if old_child else "add","kind":"channel"})
            if len(parent_sources)>256:raise ValueError("Не более 256 аппаратных источников на устройство")
            if kind=="camera" and len({c["source_key"] for c in cameras if c.get("recorder_id")==identifier})>1:raise ValueError("У отдельной IP-камеры один источник")
        if len(cameras)>4096 or len(devices)>4096:raise ValueError("Превышен размер каталога")

    def prepare_spaces(payload,mode,skip,cameras,devices,spaces,users,rows,user):
        origin=payload["origin"];local=rt.settings()["catalog_origin"]
        incoming=payload.get("spaces")
        if not isinstance(incoming,list) or len(incoming)>1000:raise ValueError("Неверный список пространств")
        source_map=object_maps(cameras,devices,spaces,local)["channels"];seen=set()
        all_zones={z["id"] for s in spaces for z in s.get("zones",[])}
        for raw in incoming:
            if not isinstance(raw,dict):raise ValueError("Неверное пространство")
            sid=schema.identifier(raw.get("id"));ident=identity(raw,origin)
            schema.identifier(ident[0]);schema.identifier(ident[1])
            if ident in seen:raise ValueError("Пространство повторяется в файле")
            seen.add(ident);old=next((s for s in spaces if identity(s,local)==ident),None)
            if sid in skip or (old and mode=="add") or (not old and mode=="update"):
                rows.append({"name":raw.get("name",sid),"action":"skip","kind":"space"});continue
            if old and access.level(user,"spaces",old["id"])!=2:abort(403)
            if not old and not access.features(user)["edit_spaces"]:abort(403)
            identifier=old["id"] if old else (sid if not any(s["id"]==sid for s in spaces) else uid("space"))
            item={"id":identifier,"name":raw.get("name"),"icon":raw.get("icon","folder"),"zones":[],"members":[],"camera_ids":[],"origin_id":ident[0],"import_id":ident[1]}
            zones=raw.get("zones",[]);members=raw.get("members",[]);zone_map={}
            if not isinstance(zones,list) or len(zones)>1000 or not isinstance(members,list) or len(members)>4096:raise ValueError("Неверный состав пространства")
            for zone in zones:
                if not isinstance(zone,dict) or zone.get("zones"):raise ValueError("Вложенные зоны не поддерживаются")
                zid=schema.identifier(zone.get("id"));zident=identity(zone,origin)
                if zid in zone_map:raise ValueError("Повторяется зона")
                previous=next((z for z in (old or {}).get("zones",[]) if identity(z,local)==zident),None)
                local_id=previous["id"] if previous else (zid if zid not in all_zones else uid("zone"))
                all_zones.add(local_id);zone_map[zid]=local_id
                item["zones"].append({"id":local_id,"name":zone.get("name"),"icon":zone.get("icon","map-pin"),"origin_id":zident[0],"import_id":zident[1]})
            for member in members:
                if not isinstance(member,dict):raise ValueError("Неверная ссылка на камеру")
                ref=schema.identifier(member.get("source_id"));ref_origin=schema.identifier(member.get("origin_id") or origin)
                zid=member.get("zone_id")
                if zid is not None and zid not in zone_map:raise ValueError("Ссылка на отсутствующую зону")
                previous=next((m for m in (old or {}).get("members",[]) if m.get("source_id")==ref and (m.get("origin_id") or origin)==ref_origin),None)
                confirmed=(previous or {}).get("channel_id")
                cid=confirmed if confirmed in {c["id"] for c in cameras} else source_map.get((ref_origin,ref))
                if cid and cid not in {c["id"] for c in rt.catalog_devices(user)}:abort(403)
                if cid and not rt.can_edit_camera(user,cid):abort(403)
                if not cid and user["role"]!="admin" and not previous:abort(403)
                entry={"id":schema.identifier(member.get("id") or uid("member")),"source_id":ref,"origin_id":ref_origin,"channel_id":cid,"zone_id":zone_map.get(zid)}
                if member.get("name"):entry["name"]=text(member["name"],"Камера",150)
                item["members"].append(entry)
            item["camera_ids"]=[m["channel_id"] for m in item["members"] if m["channel_id"]]
            validated=schema.spaces([item],{c["id"] for c in cameras})[0]
            validated.update(origin_id=ident[0],import_id=ident[1])
            for zone,validated_zone in zip(item["zones"],validated["zones"]):
                validated_zone.update(origin_id=zone["origin_id"],import_id=zone["import_id"])
            if old:spaces[spaces.index(old)]=validated
            else:
                spaces.append(validated)
                if user["role"]!="admin":next(u for u in users if u["username"]==user["username"])["grants"]["spaces"][identifier]="edit"
            rows.append({"name":validated["name"],"action":"update" if old else "add","kind":"space",
                         "pending":sum(not m["channel_id"] for m in validated["members"])})
        if len(spaces)>1000:raise ValueError("Слишком много пространств")

    def prepare_users(payload,mode,skip,cameras,devices,spaces,users,rows,user):
        incoming=payload.get("users");origin=payload["origin"];local=rt.settings()["catalog_origin"]
        if not isinstance(incoming,list) or len(incoming)>1000:raise ValueError("Неверный список пользователей")
        maps=object_maps(cameras,devices,spaces,local);seen=set()
        for raw in incoming:
            if not isinstance(raw,dict):raise ValueError("Неверный пользователь")
            if raw.get("role","viewer") not in ("viewer","admin"):raise ValueError("Неверная роль пользователя")
            login=text(raw.get("username"),"Логин",64,True)
            if login.casefold() in seen:raise ValueError("Логин повторяется в файле")
            seen.add(login.casefold());old=next((u for u in users if u["username"].casefold()==login.casefold()),None)
            if login in skip or raw.get("role")=="admin" or (old and old["role"]=="admin") or (old and mode=="add") or (not old and mode=="update"):
                rows.append({"name":login,"action":"skip","kind":"user","reason":"admin" if raw.get("role")=="admin" or (old and old["role"]=="admin") else "mode"});continue
            raw_grants=schema.grants(raw.get("grants",{}));references=raw.get("references",{})
            if not isinstance(references,dict) or set(references)-set(access.KINDS):raise ValueError("Неверные ссылки прав")
            actual={kind:{} for kind in access.KINDS};pending=[]
            for kind in access.KINDS:
                refs=references.get(kind,{})
                if not isinstance(refs,dict):raise ValueError("Неверные ссылки прав")
                for identifier,level in raw_grants[kind].items():
                    ref=refs.get(identifier,{"origin_id":origin,"source_id":identifier})
                    if not isinstance(ref,dict):raise ValueError("Неверная ссылка права")
                    key=(schema.identifier(ref.get("origin_id") or origin),schema.identifier(ref.get("source_id")))
                    local_id=maps[kind].get(key)
                    if local_id:actual[kind][local_id]=level
                    else:pending.append({"kind":kind,"origin_id":key[0],"source_id":key[1],"level":level})
            for ref in raw.get("pending_grants",[]):
                if not isinstance(ref,dict) or ref.get("kind") not in access.KINDS or ref.get("level") not in ("read","edit"):raise ValueError("Неверное отложенное право")
                pending.append({"kind":ref["kind"],"origin_id":schema.identifier(ref.get("origin_id")),"source_id":schema.identifier(ref.get("source_id")),"level":ref["level"]})
            data={k:raw[k] for k in ("alias","avatar","theme","language","permissions") if k in raw}
            data.update(username=old["username"] if old else login,role="viewer",grants=actual,active=old.get("active",True) if old else False)
            previous=old or {"username":login,"role":"viewer","active":False,"password_hash":""}
            cleaned=request_user_payload(data,previous);cleaned["pending_grants"]=pending
            if old:users[users.index(old)]=cleaned
            else:users.append(cleaned)
            rows.append({"name":login,"action":"update" if old else "add","kind":"user","pending":len(pending),"inactive":not cleaned["active"]})
        if len(users)>1000:raise ValueError("Слишком много пользователей")

    @bp.post("/api/transfers/<kind>/preview")
    def preview(kind):
        if kind not in ("devices","spaces","users"):abort(404)
        user=require(kind);data=body();payload=data.get("payload");protected=False
        if not isinstance(payload,dict):raise ValueError("Выберите JSON VWSHub")
        if payload.get("format")=="vwshub.devices.protected":
            if kind!="devices" or user["role"]!="admin":abort(403)
            payload=decrypt_payload(payload,data.get("passphrase"));protected=True
        if not isinstance(payload,dict) or payload.get("format")!="vwshub."+kind or type(payload.get("version")) is not int or payload.get("version")!=1:
            raise ValueError("Неизвестный тип или версия файла. Используйте экспорт соответствующего раздела VWSHub 0.8.5")
        schema.identifier(payload.get("origin"))
        mode=data.get("mode","add")
        if mode not in ("add","merge","update"):raise ValueError("Неизвестный режим импорта")
        skip=data.get("skip",[])
        if not isinstance(skip,list) or len(skip)>4096:raise ValueError("Неверный список пропуска")
        skip={transfer_id(kind,i) for i in skip}
        with rt.store.lock:
            cameras,devices,spaces,users=snapshot();rows=[]
            if kind=="devices":prepare_devices(payload,mode,skip,cameras,devices,spaces,users,rows,user,protected)
            elif kind=="spaces":prepare_spaces(payload,mode,skip,cameras,devices,spaces,users,rows,user)
            else:prepare_users(payload,mode,skip,cameras,devices,spaces,users,rows,user)
            spaces=normalize_spaces(spaces,cameras)
            resolve_pending(users,cameras,devices,spaces,rt.settings()["catalog_origin"])
            revision=rt.store.revision
        now=time.monotonic()
        for token in list(plans):
            if plans[token]["expires"]<now:plans.pop(token,None)
        if len(plans)>=30:plans.pop(next(iter(plans)))
        token=uid("preview")
        plans[token]={"kind":kind,"owner":user["username"],"revision":revision,"expires":now+300,
                      "catalog":(cameras,devices,spaces,users),"rows":rows}
        return jsonify(token=token,rows=rows,counts={action:sum(r["action"]==action for r in rows) for action in ("add","update","skip")},
                       pending=sum(r.get("pending",0) for r in rows),expires_seconds=300,revision=revision)

    @bp.post("/api/transfers/<kind>/apply")
    def apply(kind):
        user=require(kind);data=body();token=data.get("token")
        if not isinstance(token,str):raise ValueError("Сначала получите предварительный просмотр")
        plan=plans.get(token)
        if not plan or plan["kind"]!=kind or plan["owner"]!=user["username"] or plan["expires"]<time.monotonic():
            raise ValueError("Предварительный просмотр устарел")
        with rt.store.lock:
            if rt.store.revision!=plan["revision"]:return jsonify(error="Каталог изменился. Повторите предварительный просмотр"),409
            before={c["id"]:c for c in rt.store.get_devices()}
            cameras,devices,spaces,users=plan["catalog"]
            commit_catalog(rt,cameras,devices,spaces,users)
        plans.pop(token,None)
        if kind=="devices":
            from .core import connection_signature
            invalidate=app.extensions.get("vwshub_invalidate_camera")
            if invalidate:
                for camera in cameras:
                    old=before.get(camera["id"])
                    if old and connection_signature(old)!=connection_signature(camera):invalidate(camera["id"])
        rt.audit("catalog.imported",{"kind":kind,"rows":len(plan["rows"])})
        return jsonify(success=True)

    @bp.post("/api/users/<username>/clone")
    def clone_user(username):
        require("users");data=body()
        with rt.store.lock:
            users=rt.store.get_users();source=next((u for u in users if u["username"]==username),None)
            if not source:abort(404)
            template={k:copy.deepcopy(source[k]) for k in ("alias","avatar","theme","language","grants","permissions","pending_grants") if k in source}
            template.update(username=text(data.get("username"),"Логин копии",64,True),role="viewer",active=False,password_hash="")
            if source["role"]=="admin":template.update(grants={kind:{} for kind in access.KINDS},permissions={**access.features(template),"archive_export":False})
            chosen={k:data[k] for k in ("username","alias","password","grants","permissions") if k in data}
            chosen["active"]=bool(data.get("password"))
            result=request_user_payload(chosen,template)
            validate_user_grants(result,rt)
            if any(u["username"].casefold()==result["username"].casefold() for u in users):return jsonify(error="Логин уже существует"),409
            if len(users)>=1000:raise ValueError("Слишком много пользователей")
            users.append(result);rt.store.save_users(users)
        rt.audit("user.cloned",{"source":username,"login":result["username"]})
        return jsonify(success=True,user=public_user(result)),201

    app.register_blueprint(bp)
