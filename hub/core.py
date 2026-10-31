"""Authentication, authorization, catalog, customization and server operations."""
from __future__ import annotations

import base64
import functools
import io
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import uuid
import zipfile
from collections import defaultdict,deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

from flask import Flask,abort,current_app,g,has_request_context,jsonify,redirect,render_template,request,send_file,session,url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash,generate_password_hash

from .store import DataStore,DataCorruptError,DEFAULT_SETTINGS,safe_image
from . import access, schema

VERSION="0.8.5"
DEVELOPER="sedukindv"
REPOSITORY="https://github.com/sedukindv/VWSHub"
LOGIN_RE=re.compile(r"[A-Za-z0-9_.@-]{1,64}\Z")
IDENTIFIER_RE=re.compile(r"[A-Za-z0-9_-]{1,100}\Z")

def public_user(user):
    if not user:return None
    return {"username":user.get("username",""),"login":user.get("username",""),"alias":user.get("alias") or user.get("username",""),
            "avatar":user.get("avatar", ""),"role":user.get("role","viewer"),"theme":user.get("theme","auto"),"language":user.get("language","ru"),
            "group_ids":list(user.get("group_ids",[])),"group_access":{gid:user.get("group_access",{}).get(gid,"read") for gid in user.get("group_ids",[])},
            "archive_access":access.features(user)["archive_view"],"permissions":access.features(user),
            "grants":access.grants(user),"active":user.get("active",True),"can_edit":access.editor(user),"pending_grants":user.get("pending_grants",[])}

def public_device(device,connection=True):
    private={"password","password_hash","secret"}
    if not connection:private.update({"username","rtsp_path","rtsp_sub_path","profile_token","rtsp_host"})
    return {key:value for key,value in device.items() if key not in private}

def body():
    value=request.get_json(silent=True)
    if not isinstance(value,dict):raise ValueError("Ожидается JSON-объект")
    return value

def text(value,label,limit=150,required=False):
    if value is None:value=""
    if not isinstance(value,str):raise ValueError(f"{label}: ожидается текст")
    value=value.strip()
    if len(value)>limit or any(ord(ch)<32 for ch in value):raise ValueError(f"{label}: недопустимое значение")
    if required and not value:raise ValueError(f"Укажите {label.lower()}")
    return value

def integer(value,label,min_value,max_value):
    if isinstance(value,bool):raise ValueError(f"{label}: ожидается число")
    try:result=int(value)
    except (TypeError,ValueError,OverflowError):raise ValueError(f"{label}: ожидается целое число") from None
    if str(result)!=str(value).strip() and not isinstance(value,int):raise ValueError(f"{label}: ожидается целое число")
    if not min_value<=result<=max_value:raise ValueError(f"{label}: допустимо {min_value}–{max_value}")
    return result

def ids(value,label="Идентификаторы"):
    if not isinstance(value,list) or len(value)>4096:raise ValueError(f"{label}: ожидается список")
    if any(not isinstance(x,str) or not IDENTIFIER_RE.fullmatch(x) for x in value):raise ValueError(f"{label}: некорректный идентификатор")
    return list(dict.fromkeys(value))

def password(value):
    if not isinstance(value,str) or len(value)<10 or len(value)>256:raise ValueError("Пароль должен содержать от 10 до 256 символов")
    return value

def admin_required(function):
    @functools.wraps(function)
    def wrapped(*args,**kwargs):
        user=current_app.extensions["vwshub"].current_user()
        if not user or user.get("role")!="admin":return jsonify(error="Доступно только администратору"),403
        return function(*args,**kwargs)
    return wrapped

class Runtime:
    def __init__(self,store):
        self.store=store;self.started=time.monotonic();self.login_attempts=defaultdict(deque);self.login_lock=threading.Lock()
        self.enc_pwd=store.enc_pwd;self.dec_pwd=store.dec_pwd
        from .diagnostics import HardwareJournal
        self.hardware=HardwareJournal(store)
    def current_user(self):
        if not has_request_context():return None
        if hasattr(g,"vwshub_user"):return g.vwshub_user
        name=session.get("username")
        if session.get("auth_epoch")!=self.settings().get("auth_epoch"):
            g.vwshub_user=None;return None
        g.vwshub_user=dict(self.user_catalog().get(name,{})) or None if name else None
        if g.vwshub_user and g.vwshub_user.get("active") is False:g.vwshub_user=None
        return g.vwshub_user
    def user_catalog(self):
        with self.store.lock:
            if getattr(self,"_users_revision",None)!=self.store.revision:
                self._user_catalog={u["username"]:u for u in self.store.get_users()}
                self._users_revision=self.store.revision
            return self._user_catalog
    def catalog_index(self):
        with self.store.lock:
            if getattr(self,"_catalog_revision",None)!=self.store.revision:
                self._catalog={"cameras":{c["id"]:c for c in self.store.get_devices()},"spaces":self.store.get_groups(),
                               "parents":{d["id"]:d for d in self.store.get_recorders()}}
                self._catalog_revision=self.store.revision
            return self._catalog
    def get_camera(self,cam_id):
        camera=self.catalog_index()["cameras"].get(str(cam_id))
        return dict(camera) if camera else None
    def settings(self):return self.store.get_settings()
    def can_access_archive(self,user=None):
        user=user if user is not None else self.current_user()
        return bool(user and user.get("active") is not False and access.features(user)["archive_view"])
    def can_export_archive(self,user=None):
        user=user if user is not None else self.current_user()
        return bool(user and user.get("active") is not False and access.features(user)["archive_export"])
    def catalog_devices(self,user=None):
        user=user if user is not None else self.current_user()
        if not user or user.get("active") is False:return []
        index=self.policy_index(user)
        return [c for c in index["cameras"].values() if index["levels"].get(c["id"],0)>0]
    def policy_index(self,user):
        # All callers obtain users from the persisted catalog. Catalog writes invalidate the index.
        with self.store.lock:
            revision=self.store.revision
            if getattr(self,"_policy_revision",None)!=revision:
                self._policy_revision=revision;self._policy_indexes={}
            key=user.get("username")
            if key not in self._policy_indexes:
                # A request may still hold g.user from before a concurrent revoke.
                # Never use that old object to populate a newer revision's cache.
                persisted=self.user_catalog().get(key)
                catalog=self.catalog_index()
                levels,memberships=access.source_levels(persisted,catalog["cameras"].values(),catalog["spaces"])
                if len(self._policy_indexes)>=64:self._policy_indexes.pop(next(iter(self._policy_indexes)))
                self._policy_indexes[key]={"cameras":catalog["cameras"],"levels":levels,"memberships":memberships,"parents":catalog["parents"]}
            return self._policy_indexes[key]
    def visible_devices(self,user=None):
        user=user if user is not None else self.current_user()
        return [device for device in self.catalog_devices(user) if not device.get("is_hidden")]
    def can_access_camera(self,user,cam_id):
        if not user or user.get("active") is False:return False
        index=self.policy_index(user);camera=index["cameras"].get(str(cam_id))
        return bool(camera and not camera.get("is_hidden") and index["levels"].get(str(cam_id),0))
    def can_edit_group(self,user,group_id):
        return access.level(user,"spaces",group_id)==2
    def can_edit_camera(self,user,cam_id):
        return bool(user and self.policy_index(user)["levels"].get(str(cam_id),0)==2)
    def audit(self,action,detail=None):
        user=self.current_user()
        self.store.audit(user.get("username") if user else "system",action,detail)
    def first_setup(self):return not any(u.get("role")=="admin" for u in self.store.get_users())

def csrf_token():
    if not session.get("csrf_token"):session["csrf_token"]=secrets.token_urlsafe(32)
    return session["csrf_token"]


def validate_user_grants(user,runtime):
    spaces=runtime.store.get_groups()
    known={"spaces":{s["id"] for s in spaces},"zones":{z["id"] for s in spaces for z in s.get("zones",[])},
           "channels":{c["id"] for c in runtime.store.get_devices()},"devices":{d["id"] for d in runtime.store.get_recorders()}}
    if any(set(scope)-known[kind] for kind,scope in access.grants(user).items()):
        raise ValueError("Выбран несуществующий объект доступа. Обновите каталог")

def public_settings(runtime):
    settings=runtime.settings()
    return {"version":VERSION,"developer":DEVELOPER,"repository":REPOSITORY,"timezone":settings["timezone"],"language":settings["language"],
            "snapshot_format":settings["snapshot_format"],"archive_format":settings["archive_format"],"resource_profile":settings["resources"]["profile"],
            "max_live_streams":settings["resources"]["max_live_streams"]}

def request_user_payload(data,existing=None):
    result=dict(existing or {})
    login=text(data.get("username",data.get("login",result.get("username",""))),"Логин",64,True)
    if not LOGIN_RE.fullmatch(login):raise ValueError("Логин: латинские буквы, цифры, _, ., @ или -")
    result["username"]=login
    result["alias"]=text(data.get("alias",result.get("alias",login)),"Псевдоним",100) or login
    result["avatar"]=safe_image(data.get("avatar",result.get("avatar","")))
    result["role"]=data.get("role",result.get("role","viewer"))
    if not isinstance(result["role"],str) or result["role"] not in {"admin","viewer"}:raise ValueError("Роль: admin или viewer")
    result["theme"]=data.get("theme",result.get("theme","auto"))
    if not isinstance(result["theme"],str) or result["theme"] not in {"auto","dark","light"}:raise ValueError("Неизвестная тема")
    result["language"]=data.get("language",result.get("language","ru"))
    if not isinstance(result["language"],str) or result["language"] not in {"ru","en"}:raise ValueError("Язык: ru или en")
    result["group_ids"]=ids(data.get("group_ids",result.get("group_ids",[])),"Группы пользователя")
    group_access=data.get("group_access",{gid:level for gid,level in result.get("group_access",{}).items() if gid in result["group_ids"]})
    if not isinstance(group_access,dict) or set(group_access)-set(result["group_ids"]) or any(not isinstance(v,str) or v not in {"read","edit"} for v in group_access.values()):raise ValueError("Права групп: только read/edit для назначенных групп")
    result["group_access"]={gid:group_access.get(gid,"read") for gid in result["group_ids"]}
    if "archive_access" in data and not isinstance(data["archive_access"],bool):raise ValueError("archive_access: ожидается логическое значение")
    result["archive_access"]=True if result["role"]=="admin" else data.get("archive_access",result.get("archive_access",False))
    if "active" in data:
        if not isinstance(data["active"],bool):raise ValueError("active: ожидается логическое значение")
        result["active"]=data["active"]
    if "grants" in data:
        value=data["grants"]
        if not isinstance(value,dict) or set(value)-set(access.KINDS):raise ValueError("Некорректные области доступа")
        clean={}
        for kind in access.KINDS:
            scope=value.get(kind,{})
            if not isinstance(scope,dict) or len(scope)>4096:raise ValueError("Некорректная область доступа")
            ids(list(scope))
            if any(v not in ("read","edit") for v in scope.values()):raise ValueError("Права: read или edit")
            clean[kind]=dict(scope)
        result["grants"]=clean;result["group_ids"]=list(clean["spaces"]);result["group_access"]=clean["spaces"]
    elif "group_ids" in data or "group_access" in data:
        result["grants"]={**access.grants(result),"spaces":dict(result["group_access"])}
    if "permissions" in data:
        value=data["permissions"]
        if isinstance(value,dict) and "create_spaces" in value:
            value=dict(value);legacy=value.pop("create_spaces")
            if not isinstance(legacy,bool):raise ValueError("Некорректные разрешения")
            value.setdefault("edit_spaces",bool(legacy or any(v=="edit" for kind in ("spaces","zones") for v in access.grants(result)[kind].values())))
        if not isinstance(value,dict) or set(value)-set(access.FEATURES) or any(not isinstance(v,bool) for v in value.values()):raise ValueError("Некорректные разрешения")
        result["permissions"]={**access.features(result),**value}
        if result["permissions"]["archive_export"] and not result["permissions"]["archive_view"]:raise ValueError("Для скачивания нужен просмотр архива")
    elif "archive_access" in data:
        result["permissions"]={**access.features(result),"archive_view":result["archive_access"]}
    if data.get("password"):result["password_hash"]=generate_password_hash(password(data["password"]))
    elif not existing:raise ValueError("Укажите пароль нового пользователя")
    if result.get("active",True) and not result.get("password_hash"):raise ValueError("Для активации задайте пароль пользователя")
    if data.get("clear_pending_grants") is True:result["pending_grants"]=[]
    return access.normalize_user(result)

def validate_device(data,existing,runtime):
    source=dict(existing or {});source.update(data)
    name=text(source.get("name"),"Название",150,True)
    host=text(source.get("ip"),"IP-адрес или имя узла",253,True)
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+",host) or ".." in host:raise ValueError("Укажите IP-адрес или DNS-имя без URL и пути")
    protocol=source.get("protocol","dvrip")
    if not isinstance(protocol,str) or protocol not in {"dvrip","onvif"}:raise ValueError("Протокол: dvrip или onvif")
    # A protocol switch replaces its inherited default port, unless the caller explicitly chose a port.
    default_port=34567 if protocol=="dvrip" else 80
    port=data.get("port",default_port if existing and protocol!=existing.get("protocol") else source.get("port",default_port))
    result={"id":source.get("id") or "cam_"+uuid.uuid4().hex,"name":name,"ip":host,"protocol":protocol,
            "port":integer(port,"Порт протокола",1,65535),"rtsp_port":integer(source.get("rtsp_port",554),"Порт RTSP",1,65535),
            "username":text(source.get("username",""),"Логин устройства",128),"password":existing.get("password","") if existing else ""}
    if not isinstance(result["id"],str) or not IDENTIFIER_RE.fullmatch(result["id"]):raise ValueError("Некорректный идентификатор устройства")
    if "password" in data:
        if not isinstance(data["password"],str) or len(data["password"])>256:raise ValueError("Некорректный пароль устройства")
        if data["password"] or not existing:result["password"]=runtime.enc_pwd(data["password"])
    if protocol=="dvrip":result["channel"]=integer(source.get("channel",0),"Канал",0,255)
    else:
        if source.get("rtsp_host"):
            rtsp_host=text(source["rtsp_host"],"Узел RTSP",253,True)
            if not re.fullmatch(r"[A-Za-z0-9_.:-]+",rtsp_host) or ".." in rtsp_host:raise ValueError("Некорректный узел RTSP")
            result["rtsp_host"]=rtsp_host
        for key in ("rtsp_path","rtsp_sub_path"):
            value=text(source.get(key,""),"Путь RTSP",2048)
            if "://" in value:raise ValueError("Укажите только путь RTSP без адреса и учётных данных")
            result[key]=value
    # Explicitly preserve known connection metadata without accepting arbitrary data-file fields.
    for key in ("profile_token","audio_enabled"):
        if key in source:
            if key=="profile_token":result[key]=text(source[key],"Профиль ONVIF",256)
            elif not isinstance(source[key],bool):raise ValueError("audio_enabled: ожидается логическое значение")
            else:result[key]=source[key]
    for key in ("recorder_id","source_key","source_token","is_hidden","visibility_revision","origin_id","import_id","alias_of"):
        if existing and key in existing:result[key]=existing[key]
    return result


def connection_signature(camera):
    protocol=camera.get("protocol","dvrip");host=str(camera.get("ip","")).lower()
    return (protocol,host,int(camera.get("port") or (34567 if protocol=="dvrip" else 80)),int(camera.get("rtsp_port") or 554),
            str(camera.get("rtsp_host") or host).lower(),camera.get("username") or "",camera.get("password") or "",
            int(camera.get("channel") or 0),camera.get("rtsp_path") or "",camera.get("rtsp_sub_path") or "",camera.get("profile_token") or "")

def register_core(app,runtime):
    app.extensions["vwshub"]=runtime
    @app.before_request
    def protect_request():
        g.catalog_start_revision=runtime.store.revision
        if getattr(runtime,"maintenance",False) and request.endpoint!="health":return jsonify(error="Восстанавливается backup. Повторите запрос через несколько секунд"),503
        is_api=request.path.startswith("/api/")
        public=request.endpoint in {"static","login","setup","health","bootstrap","favicon"} or request.path=="/api/branding" and request.method=="GET"
        if not public:
            user=runtime.current_user()
            if not user:
                if is_api or request.path.startswith("/live/"):return jsonify(error="Требуется авторизация"),401
                return redirect(url_for("setup" if runtime.first_setup() else "login"))
        if request.method in {"POST","PUT","PATCH","DELETE"}:
            origin=request.headers.get("Origin")
            if origin and origin.rstrip("/")!=request.host_url.rstrip("/"):return jsonify(error="Запрос с другого сайта отклонён"),403
            if app.config.get("CSRF_ENABLED",True):
                submitted=request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
                expected=session.get("csrf_token")
                if not expected or not submitted or not secrets.compare_digest(str(expected),str(submitted)):
                    return jsonify(error="Обновите страницу: токен сеанса отсутствует или устарел"),403

    @app.after_request
    def response_headers(response):
        media=app.extensions.get("vwshub_media")
        if media and getattr(g,"catalog_start_revision",runtime.store.revision)!=runtime.store.revision:
            media.reconcile_permissions()
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="same-origin"
        response.headers["X-Frame-Options"]="SAMEORIGIN"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; worker-src 'self' blob:; connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        if request.path.startswith("/api/") or request.endpoint in {"index","login","setup"}:response.headers["Cache-Control"]="no-store"
        return response

    @app.errorhandler(ValueError)
    def invalid(error):return jsonify(error=str(error)),400
    @app.errorhandler(DataCorruptError)
    def corrupt(error):return jsonify(error=str(error)),503
    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/") or request.path.startswith("/live/"):return jsonify(error=error.description),error.code
        return error

    def template(name,**extra):return render_template(name,user=public_user(runtime.current_user()),branding=runtime.settings()["branding"],settings=public_settings(runtime),csrf_token=csrf_token(),first_setup=runtime.first_setup(),**extra)

    @app.get("/health")
    def health():return jsonify(status="ok",version=VERSION)
    @app.get("/api/bootstrap")
    def bootstrap():return jsonify(user=public_user(runtime.current_user()),branding=runtime.settings()["branding"],setup_required=runtime.first_setup(),csrf_token=csrf_token(),public_settings=public_settings(runtime))
    @app.route("/setup",methods=["GET","POST"])
    def setup():
        if not runtime.first_setup():return redirect(url_for("index" if runtime.current_user() else "login"))
        if request.method=="GET":return template("setup.html")
        data=body() if request.is_json else request.form.to_dict()
        try:
            if "password_confirm" in data and data["password_confirm"]!=data.get("password"):raise ValueError("Пароли не совпадают")
            new=request_user_payload({**data,"role":"admin","archive_access":True,"group_ids":[]})
            with runtime.store.lock:
                users=runtime.store.get_users()
                if any(u.get("role")=="admin" for u in users):return jsonify(error="Первый администратор уже создан"),409
                if any(u.get("username")==new["username"] for u in users):raise ValueError("Такой логин уже существует")
                users.append(new);runtime.store.save_users(users)
            session.clear();session["username"]=new["username"];session["auth_epoch"]=runtime.settings().get("auth_epoch");session.permanent=True;csrf_token();runtime.audit("setup.admin_created")
            return jsonify(success=True,user=public_user(new),csrf_token=csrf_token()) if request.is_json else redirect(url_for("index"))
        except ValueError as exc:
            return (jsonify(error=str(exc)),400) if request.is_json else (template("setup.html",error=str(exc)),400)
    @app.route("/login",methods=["GET","POST"])
    def login():
        if runtime.first_setup():return redirect(url_for("setup"))
        if request.method=="GET":return template("login.html")
        data=body() if request.is_json else request.form
        login_name=str(data.get("username",data.get("login",""))).strip();supplied=str(data.get("password",""))
        address=request.remote_addr or "unknown";now=time.monotonic()
        with runtime.login_lock:
            recent=runtime.login_attempts[address]
            while recent and recent[0]<now-60:recent.popleft()
            if len(recent)>=8:return jsonify(error="Слишком много попыток. Повторите через минуту."),429
            recent.append(now)
        user=next((u for u in runtime.store.get_users() if u.get("username")==login_name),None)
        if not user or user.get("active") is False or not check_password_hash(user.get("password_hash",""),supplied):
            runtime.store.audit(login_name or "anonymous","auth.login_failed",{})
            return (jsonify(error="Неверный логин или пароль"),401) if request.is_json else (template("login.html",error="Неверный логин или пароль"),401)
        with runtime.login_lock:runtime.login_attempts.pop(address,None)
        session.clear();session["username"]=user["username"];session["auth_epoch"]=runtime.settings().get("auth_epoch");session.permanent=True;csrf_token();runtime.audit("auth.login")
        return jsonify(success=True,user=public_user(user),csrf_token=csrf_token()) if request.is_json else redirect(url_for("index"))
    @app.route("/logout",methods=["GET","POST"])
    def logout():
        runtime.audit("auth.logout");session.clear();return redirect(url_for("login"))
    @app.get("/")
    def index():return template("index.html")
    @app.get("/favicon.ico")
    def favicon():
        value=runtime.settings()["branding"].get("favicon","")
        if value:
            metadata,encoded=value.split(",",1)
            return send_file(io.BytesIO(base64.b64decode(encoded)),mimetype=metadata.split(";")[0][5:])
        return "",204

    @app.route("/api/profile",methods=["GET","POST"])
    def profile():
        me=runtime.current_user()
        if request.method=="GET":return jsonify(public_user(me))
        data=body()
        with runtime.store.lock:
            users=runtime.store.get_users();target=next(u for u in users if u["username"]==me["username"])
            for key in ("alias","avatar","theme","language"):
                if key not in data:continue
                if key=="alias":target[key]=text(data[key],"Псевдоним",100) or target["username"]
                elif key=="avatar":target[key]=safe_image(data[key])
                elif key=="theme":
                    if data[key] not in {"auto","dark","light"}:raise ValueError("Неизвестная тема")
                    target[key]=data[key]
                elif key=="language":
                    if data[key] not in {"ru","en"}:raise ValueError("Язык: ru или en")
                    target[key]=data[key]
            if data.get("password"):
                if not check_password_hash(target["password_hash"],str(data.get("current_password",""))):raise ValueError("Для смены пароля укажите текущий пароль")
                target["password_hash"]=generate_password_hash(password(data["password"]))
            runtime.store.save_users(users)
        runtime.audit("profile.updated");return jsonify(success=True,user=public_user(target))
    @app.post("/api/profile/theme")
    def profile_theme():return profile()

    @app.route("/api/users",methods=["GET","POST"])
    @admin_required
    def users():
        if request.method=="GET":return jsonify([public_user(u) for u in runtime.store.get_users()])
        data=body();new=request_user_payload(data)
        with runtime.store.lock:
            validate_user_grants(new,runtime)
            values=runtime.store.get_users()
            if any(u["username"].casefold()==new["username"].casefold() for u in values):return jsonify(error="Логин уже существует"),409
            if len(values)>=1000:raise ValueError("Каталог поддерживает до 1000 пользователей")
            values.append(new);runtime.store.save_users(values)
        runtime.audit("user.created",{"login":new["username"],"role":new["role"]});return jsonify(success=True,user=public_user(new)),201
    @app.route("/api/users/<username>",methods=["PUT","DELETE"])
    @admin_required
    def user_manage(username):
        with runtime.store.lock:
            values=runtime.store.get_users();old=next((u for u in values if u["username"]==username),None)
            if not old:abort(404,description="Пользователь не найден")
            if request.method=="DELETE":
                if username==runtime.current_user()["username"]:raise ValueError("Нельзя удалить текущий аккаунт")
                if old.get("role")=="admin" and sum(u.get("role")=="admin" for u in values)<2:raise ValueError("Нельзя удалить последнего администратора")
                values.remove(old)
            else:
                data=body();data["username"]=username;new=request_user_payload(data,old)
                if username==runtime.current_user()["username"] and (new["role"]!="admin" or not new["active"]):raise ValueError("Нельзя отключить или понизить роль текущего администратора")
                validate_user_grants(new,runtime)
                if old.get("role")=="admin" and new["role"]!="admin" and sum(u.get("role")=="admin" for u in values)<2:raise ValueError("Нельзя понизить последнего администратора")
                values[values.index(old)]=new
            runtime.store.save_users(values)
        runtime.audit("user.deleted" if request.method=="DELETE" else "user.updated",{"login":username});return jsonify(success=True)

    def camera_list():
        user=runtime.current_user();groups=runtime.store.get_groups()
        recorder_names={r["id"]:r["name"] for r in runtime.store.get_recorders()}
        permitted={g["id"] for g in groups} if user["role"]=="admin" else set(user.get("group_ids",[]))
        result=[]
        for camera in runtime.visible_devices(user):
            item=public_device(camera,connection=user["role"]=="admin");members=[g for g in groups if g["id"] in permitted and camera["id"] in g.get("camera_ids",[])]
            item.update(group_ids=[g["id"] for g in members],group_names=[g["name"] for g in members],has_password=bool(camera.get("password")),
                        recorder_name=recorder_names.get(camera.get("recorder_id"),camera["ip"]),can_edit=runtime.can_edit_camera(user,camera["id"]))
            result.append(item)
        return result
    def assign_groups(cam_id,chosen,groups):
        if set(chosen)-{g["id"] for g in groups}:raise ValueError("Выбрана несуществующая группа")
        for group in groups:
            members=[c for c in group.get("camera_ids",[]) if c!=cam_id]
            if group["id"] in chosen:members.append(cam_id)
            group["camera_ids"]=members
    def invalidate_device(cam_id):
        media=app.extensions.get("vwshub_media")
        if not media:return
        for stream in ("main","sub"):media.live.stop(cam_id,stream)
        with media.lock:
            media.files={key:value for key,value in media.files.items() if key[0]!=str(cam_id)}
            media.audio_cache.pop(str(cam_id),None)
            operations=[value for value in getattr(media,"operations",{}).values() if value.get("camera")==str(cam_id)]
        for operation in operations:operation["cancel"]()
    app.extensions["vwshub_invalidate_camera"]=invalidate_device
    @app.route("/api/cameras",methods=["GET","POST"])
    def cameras():
        if request.method=="GET":return jsonify(camera_list())
        if runtime.current_user()["role"]!="admin":abort(403)
        data=body()
        with runtime.store.lock:
            devices=runtime.store.get_devices();old=next((c for c in devices if c["id"]==data.get("id")),None)
            if not old and len(devices)>=4096:raise ValueError("Каталог поддерживает до 4096 камер")
            new=validate_device(data,old,runtime);groups=runtime.store.get_groups()
            if "group_ids" in data:assign_groups(new["id"],ids(data["group_ids"],"Группы камеры"),groups)
            if old:devices[devices.index(old)]=new
            else:devices.append(new)
            runtime.store.save_catalog(devices,groups)
        if old and connection_signature(old)!=connection_signature(new):invalidate_device(new["id"])
        runtime.audit("camera.saved",{"id":new["id"],"protocol":new["protocol"]});return jsonify(success=True,camera=public_device(new))
    @app.post("/api/cameras/<cam_id>/clone")
    @admin_required
    def clone_camera(cam_id):
        data=body()
        with runtime.store.lock:
            source=runtime.get_camera(cam_id)
            if not source:abort(404,description="Устройство не найдено")
            clone=dict(source);clone["id"]="cam_"+uuid.uuid4().hex
            clone["name"]=text(data.get("name",source["name"]+" — копия"),"Название копии",150,True)
            if "channel" in data:clone["channel"]=integer(data["channel"],"Канал",0,255)
            devices=runtime.store.get_devices()
            if len(devices)>=4096:raise ValueError("Каталог поддерживает до 4096 камер")
            devices.append(clone);groups=runtime.store.get_groups()
            chosen=ids(data["group_ids"],"Группы камеры") if "group_ids" in data else [g["id"] for g in groups if cam_id in g.get("camera_ids",[])]
            assign_groups(clone["id"],chosen,groups);runtime.store.save_catalog(devices,groups)
        runtime.audit("camera.cloned",{"source":cam_id,"id":clone["id"]});return jsonify(success=True,camera=public_device(clone),group_ids=chosen),201
    @app.delete("/api/cameras/<cam_id>")
    @admin_required
    def delete_camera(cam_id):
        with runtime.store.lock:
            devices=runtime.store.get_devices()
            if not any(c["id"]==cam_id for c in devices):abort(404)
            groups=runtime.store.get_groups()
            for group in groups:group["camera_ids"]=[x for x in group.get("camera_ids",[]) if x!=cam_id]
            runtime.store.save_catalog([c for c in devices if c["id"]!=cam_id],groups)
        invalidate_device(cam_id)
        runtime.audit("camera.deleted",{"id":cam_id});return jsonify(success=True)

    @app.route("/api/groups",methods=["GET","POST"])
    def groups():
        me=runtime.current_user();values=runtime.store.get_groups()
        if request.method=="GET":return jsonify([{**g,"access":"edit" if runtime.can_edit_group(me,g["id"]) else "read"} for g in values if me["role"]=="admin" or g["id"] in me.get("group_ids",[])])
        if me["role"]!="admin" and not any(runtime.can_edit_group(me,g["id"]) for g in values):abort(403)
        data=body();new={"id":data.get("id") or "grp_"+uuid.uuid4().hex,"name":text(data.get("name"),"Название группы",100,True),"camera_ids":ids(data.get("camera_ids",[]),"Камеры группы")}
        if not isinstance(new["id"],str) or not IDENTIFIER_RE.fullmatch(new["id"]):raise ValueError("Некорректный идентификатор группы")
        with runtime.store.lock:
            if set(new["camera_ids"])-{d["id"] for d in runtime.store.get_devices()}:raise ValueError("Выбрана несуществующая камера")
            values=runtime.store.get_groups();old=next((g for g in values if g["id"]==new["id"]),None)
            if me["role"]!="admin":
                if not old or not runtime.can_edit_group(me,old["id"]):abort(403)
                if set(new["camera_ids"])-set(old.get("camera_ids",[])):raise ValueError("Редактор может переименовать группу или убрать её камеры; добавление доступно администратору")
            camera_names=data.get("camera_names",{})
            if not isinstance(camera_names,dict):raise ValueError("Названия камер: ожидается объект")
            permitted=set(new["camera_ids"]) if me["role"]=="admin" else set(new["camera_ids"])&set(old.get("camera_ids",[]))
            if set(camera_names)-permitted:raise ValueError("Переименование доступно только для камер этой группы")
            camera_names={cid:text(name,"Название камеры",150,True) for cid,name in camera_names.items()}
            if old:
                new={**old,**new}
                values[values.index(old)]=new
            else:
                if len(values)>=1000:raise ValueError("Каталог поддерживает до 1000 групп")
                values.append(new)
            if camera_names:
                devices=runtime.store.get_devices()
                for camera in devices:
                    if camera["id"] in camera_names:camera["name"]=camera_names[camera["id"]]
                runtime.store.save_catalog(devices,values)
            else:runtime.store.save_groups(values)
        runtime.audit("group.saved",{"id":new["id"]});return jsonify(success=True,group=new)
    @app.delete("/api/groups/<group_id>")
    @admin_required
    def delete_group(group_id):
        with runtime.store.lock:
            values=runtime.store.get_groups()
            if not any(g["id"]==group_id for g in values):abort(404)
            runtime.store.save_groups([g for g in values if g["id"]!=group_id]);users=runtime.store.get_users()
            for user in users:
                user["group_ids"]=[x for x in user.get("group_ids",[]) if x!=group_id]
                user.get("grants",{}).get("spaces",{}).pop(group_id,None)
                removed=next(g for g in values if g["id"]==group_id)
                for zone in removed.get("zones",[]):user.get("grants",{}).get("zones",{}).pop(zone["id"],None)
                user.get("group_access",{}).pop(group_id,None)
            runtime.store.save_users(users)
        runtime.audit("group.deleted",{"id":group_id});return jsonify(success=True)
    @app.get("/api/groups/export")
    @admin_required
    def export_groups():
        payload={"format":"vwshub.groups","version":1,"groups":runtime.store.get_groups()}
        return send_file(io.BytesIO(json.dumps(payload,ensure_ascii=False,indent=2).encode()),mimetype="application/json",as_attachment=True,download_name="vwshub-groups.json")
    @app.post("/api/groups/import")
    @admin_required
    def import_groups():
        return jsonify(error="Прямой импорт отключён. Используйте /api/transfers/spaces/preview и /api/transfers/spaces/apply."),410

    @app.post("/api/cameras/status")
    def camera_status():
        data=body();requested=data.get("camera_ids",data.get("ids"));requested=ids(requested) if requested is not None else None
        devices=[d for d in runtime.visible_devices() if requested is None or d["id"] in requested]
        stamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
        def probe(device):
            port=int(device.get("port",34567 if device.get("protocol")=="dvrip" else 80))
            try:
                with socket.create_connection((device["ip"],port),timeout=.9):pass
                return device["id"],{"online":True,"checked_at":stamp,"port":port}
            except OSError:return device["id"],{"online":False,"checked_at":stamp,"reason":"Нет TCP-ответа на порт устройства"}
        with ThreadPoolExecutor(max_workers=min(16,max(1,len(devices)))) as pool:result=dict(pool.map(probe,devices))
        runtime.audit("camera.status_checked",{"count":len(result)});return jsonify(success=True,status=result,checked_at=stamp)

    @app.post("/api/discovery")
    @admin_required
    def discovery():
        data=body();timeout=integer(data.get("timeout",3),"Время поиска",1,8);devices=[];warnings=[];seen=set()
        subnet=text(data.get("subnet",""),"Подсеть",64)
        network=None
        if subnet:
            try:network=ipaddress.ip_network(subnet,strict=False)
            except ValueError:raise ValueError("Некорректная IPv4-подсеть") from None
            allowed=[ipaddress.ip_network(x) for x in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16")]
            if network.version!=4 or network.num_addresses>256 or not any(network.subnet_of(n) for n in allowed):raise ValueError("Для сканирования выберите локальную IPv4-подсеть не больше /24")
        try:
            from wsdiscovery.discovery import WSDiscovery
            ws=WSDiscovery();ws.start()
            try:
                for service in (ws.searchServices(timeout=timeout) or [])[:128]:
                    addresses=list(service.getXAddrs() or []);types=[str(x) for x in (service.getTypes() or [])]
                    for address in addresses:
                        parsed=urlsplit(str(address))
                        if parsed.scheme not in {"http","https"} or not parsed.hostname:continue
                        if "onvif" not in str(address).lower() and not any("NetworkVideo" in t for t in types):continue
                        key=(parsed.hostname,parsed.port or 80)
                        if key in seen:break
                        seen.add(key);devices.append({"ip":key[0],"port":key[1],"protocol":"onvif","rtsp_port":554,"name":"ONVIF "+key[0],"detected_by":"WS-Discovery"});break
            finally:ws.stop()
        except ImportError:warnings.append("WSDiscovery не установлен. Установите зависимости requirements.txt.")
        except Exception:warnings.append("WS-Discovery не ответил; проверьте multicast и интерфейс сети.")
        if network:
            def scan(host):
                try:
                    with socket.create_connection((str(host),34567),timeout=.45):pass
                    return {"ip":str(host),"port":34567,"protocol":"dvrip","rtsp_port":554,"name":"DVRIP "+str(host),"detected_by":"TCP 34567 (протокол требует проверки)"}
                except OSError:return None
            with ThreadPoolExecutor(max_workers=32) as pool:devices.extend(x for x in pool.map(scan,network.hosts()) if x)
        runtime.audit("device.discovery",{"found":len(devices),"subnet":subnet});return jsonify(success=True,devices=devices,warnings=warnings)

    @app.route("/api/branding",methods=["GET","POST"])
    def branding():
        settings=runtime.settings()
        if request.method=="GET":return jsonify(settings["branding"])
        if not runtime.current_user() or runtime.current_user()["role"]!="admin":abort(403)
        data=body();brand=dict(settings["branding"])
        for key in ("name","subtitle"):
            if key in data:brand[key]=text(data[key],"Название" if key=="name" else "Подпись",80,key=="name")
        for key in ("logo","favicon"):
            if key in data:brand[key]=safe_image(data[key])
        for key in ("logo_icon","favicon_icon"):
            if key in data:
                if not isinstance(data[key],str):raise ValueError("Некорректное имя значка")
                brand[key]="" if data[key]=="" else schema.icon(data[key])
        for color_key in ("accent","icon_color"):
            if color_key in data:
                if not isinstance(data[color_key],str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",data[color_key]):raise ValueError("Цвет: #RRGGBB")
                brand[color_key]=data[color_key]
        if "motion" in data:
            if not isinstance(data["motion"],bool):raise ValueError("Анимация: логическое значение")
            brand["motion"]=data["motion"]
        for key,allowed in {"recorder_labels":{"ip","name"},"density":{"comfortable","compact"},"corners":{"rounded","square"}}.items():
            if key in data:
                if not isinstance(data[key],str) or data[key] not in allowed:raise ValueError("Неизвестный вариант оформления: "+key)
                brand[key]=data[key]
        if "show_clock" in data:
            if not isinstance(data["show_clock"],bool):raise ValueError("Часы: логическое значение")
            brand["show_clock"]=data["show_clock"]
        if "wall_gap" in data:brand["wall_gap"]=integer(data["wall_gap"],"Расстояние между камерами",0,12)
        with runtime.store.lock:settings=runtime.settings();settings["branding"]=brand;runtime.store.save_settings(settings)
        runtime.audit("branding.updated");return jsonify(success=True,branding=brand)

    def metrics():
        result={"uptime_seconds":round(time.monotonic()-runtime.started),"cpu_percent":None,"memory_percent":None,"process_memory_mb":None,"disk":None}
        try:
            import psutil
            result.update(cpu_percent=psutil.cpu_percent(interval=None),memory_percent=psutil.virtual_memory().percent,process_memory_mb=round(psutil.Process().memory_info().rss/1048576,1))
        except ImportError:pass
        usage=shutil.disk_usage(runtime.store.base_dir);result["disk"]={"total":usage.total,"free":usage.free,"used":usage.used}
        media=app.extensions.get("vwshub_media")
        result.update(media.stats() if media else {"live_streams":0,"archive_streams":0})
        return result
    def capabilities():return {"restart":bool(app.config.get("RESTART_COMMAND")),"backup":True,"restore":True,"metrics":True,"resource_limits":True,"restore_requires_server_access":False}
    @app.route("/api/settings",methods=["GET","POST"])
    @admin_required
    def settings():
        values=runtime.settings()
        if request.method=="GET":return jsonify(settings={**values,**public_settings(runtime)},metrics=metrics(),capabilities=capabilities())
        data=body()
        if "diagnostics" in data:
            if not isinstance(data["diagnostics"],dict) or not isinstance(data["diagnostics"].get("enabled"),bool):raise ValueError("Диагностика: укажите enabled true/false")
            values["diagnostics"]={"enabled":data["diagnostics"]["enabled"]}
        if "language" in data:
            if data["language"] not in {"ru","en"}:raise ValueError("Язык: ru или en")
            values["language"]=data["language"]
        if "timezone" in data:
            try:ZoneInfo(str(data["timezone"]))
            except (ZoneInfoNotFoundError,ValueError):raise ValueError("Неизвестный часовой пояс IANA") from None
            values["timezone"]=str(data["timezone"])
        if "snapshot_format" in data:
            if data["snapshot_format"] not in {"jpeg","png","webp"}:raise ValueError("Формат снимка: jpeg/png/webp")
            values["snapshot_format"]=data["snapshot_format"]
        if "archive_format" in data and data["archive_format"]!="mp4":raise ValueError("Без перекодирования архив доступен в MP4")
        if "resources" in data:
            resource=data["resources"]
            if not isinstance(resource,dict):raise ValueError("Некорректные ограничения ресурсов")
            profile=resource.get("profile",values["resources"]["profile"])
            if profile not in {"standard","maximum","custom"}:raise ValueError("Неизвестный профиль ресурсов")
            chosen=dict(DEFAULT_SETTINGS["resources"])
            if profile=="maximum":chosen.update(max_live_streams=64,max_archive_streams=12,archive_buffer_mb=64,archive_idle_seconds=300,ffmpeg_threads=0)
            if profile=="custom":
                chosen=dict(values["resources"])
                bounds={"max_live_streams":(1,128),"max_archive_streams":(1,16),"archive_buffer_mb":(2,128),"archive_idle_seconds":(30,600),"ffmpeg_threads":(0,32)}
                for key,bound in bounds.items():
                    if key in resource:chosen[key]=integer(resource[key],key,*bound)
            chosen["profile"]=profile;values["resources"]=chosen
        with runtime.store.lock:runtime.store.save_settings(values)
        runtime.audit("settings.updated",{"resources":values["resources"],"timezone":values["timezone"]});return jsonify(success=True,settings={**values,**public_settings(runtime)},metrics=metrics(),capabilities=capabilities())
    @app.get("/api/info")
    @admin_required
    def info():return jsonify(**public_settings(runtime),metrics=metrics())
    @app.get("/api/logs")
    @admin_required
    def logs():
        limit=integer(request.args.get("limit",200),"Лимит записей",1,500)
        return jsonify(logs=runtime.store.logs(limit),version=VERSION)
    @app.get("/api/backup")
    @admin_required
    def backup():
        output=io.BytesIO()
        with runtime.store.lock,zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
            for filename in ("users.json","groups.json","devices.json","recorders.json","settings.json",".camkey",".flask_secret"):
                archive.writestr("data/"+filename,(runtime.store.base_dir/filename).read_bytes())
            archive.writestr("BACKUP.txt","VWSHub0.8. Contains encrypted credentials and their key. Keep offline/private.\n")
        output.seek(0);runtime.audit("server.backup_exported")
        return send_file(output,mimetype="application/zip",as_attachment=True,download_name="vwshub-backup-"+datetime.now().strftime("%Y%m%d-%H%M%S")+".zip")
    @app.post("/api/server/restart")
    @admin_required
    def restart():
        data=body()
        if data.get("confirm") is not True:raise ValueError("Подтвердите перезапуск сервера")
        command=app.config.get("RESTART_COMMAND")
        if not command:return jsonify(error="Перезапуск доступен при настройке VWSHUB_RESTART_COMMAND менеджером сервиса"),501
        runtime.audit("server.restart_requested")
        def dispatch():
            time.sleep(1)
            try:subprocess.Popen(command,shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except OSError:runtime.store.audit("system","server.restart_failed")
        threading.Thread(target=dispatch,daemon=True).start();return jsonify(success=True,message="Перезапуск запрошен у менеджера сервиса"),202

def create_app(data_dir=None,config=None):
    project=Path(__file__).resolve().parents[1]
    app=Flask(__name__,template_folder=str(project/"templates"),static_folder=str(project/"static"))
    app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE","0")=="1",PERMANENT_SESSION_LIFETIME=timedelta(days=7),MAX_CONTENT_LENGTH=20*1024*1024,CSRF_ENABLED=True)
    if config:app.config.update(config)
    target=Path(data_dir or os.getenv("VWSHUB_DATA_DIR") or os.getenv("WEBVMS_DATA_DIR") or project/"data")
    store=DataStore(target,app.config.get("LEGACY_DATA_DIR",project));runtime=Runtime(store)
    app.secret_key=os.getenv("FLASK_SECRET_KEY") or store.secret()
    app.config.setdefault("LIVE_ROOT",str(store.base_dir/"live"))
    configured=os.getenv("VWSHUB_RESTART_COMMAND")
    if configured and not app.config.get("RESTART_COMMAND"):
        command=json.loads(configured)
        if not isinstance(command,list) or not command or any(not isinstance(x,str) for x in command):raise RuntimeError("VWSHUB_RESTART_COMMAND must be a JSON argument array")
        app.config["RESTART_COMMAND"]=command
    register_core(app,runtime)
    from .catalog import register_catalog
    register_catalog(app,runtime)
    if app.config.get("REGISTER_EXTENSIONS",True):
        from .media import register_media
        from .devices import register_devices
        register_media(app,runtime);register_devices(app,runtime)
    from .workspace import register_workspace
    register_workspace(app,runtime)
    from .transfers import register_transfers
    register_transfers(app,runtime)
    return app
