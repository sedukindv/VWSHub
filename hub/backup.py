"""Validate application backups without extracting archive paths to disk."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import stat
import uuid
import zipfile
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet, InvalidToken

from .store import DEFAULT_SETTINGS, DataStore, safe_image
from . import schema
from .structure import physical_catalog,normalize_spaces,CONNECTION_FIELDS

FILES = {"users.json", "groups.json", "devices.json", "recorders.json", "settings.json", ".camkey", ".flask_secret"}
MAX_BYTES = 16 * 1024 * 1024


def validate_backup(raw):
    from .core import IDENTIFIER_RE, LOGIN_RE, ids, integer, text, validate_device

    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Backup: ZIP до 16 МБ")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or len(names) > 10:
                raise ValueError("В ZIP повторяются файлы или слишком много записей")
            allowed = {"data/" + name for name in FILES} | {"BACKUP.txt", "data/"}
            if set(names) - allowed:
                raise ValueError("В backup есть посторонние файлы или небезопасные пути")
            if sum(entry.file_size for entry in entries) > MAX_BYTES:
                raise ValueError("Распакованный backup превышает 16 МБ")
            for entry in entries:
                if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Зашифрованные ZIP и символические ссылки не поддерживаются")
            required = {"data/" + name for name in FILES - {"recorders.json"}}
            if required - set(names):
                raise ValueError("Backup не содержит всех файлов данных и ключей")
            contents = {name: archive.read("data/" + name) for name in FILES if "data/" + name in names}
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError, NotImplementedError, UnicodeError):
        raise ValueError("Не удалось прочитать ZIP backup") from None

    try:
        camera_key = contents[".camkey"].strip()
        cipher = Fernet(camera_key)
        secret = contents[".flask_secret"].decode("utf-8").strip()
        if not 32 <= len(secret) <= 256 or not re.fullmatch(r"[A-Za-z0-9_./+=-]+", secret):
            raise ValueError("Некорректный ключ сеансов")
        parsed = {name: json.loads(contents.get(name, b"[]").decode("utf-8-sig")) for name in FILES if name.endswith(".json")}
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise ValueError("Некорректные JSON или ключи backup") from None

    users, groups, cameras, recorders = (parsed[name] for name in ("users.json", "groups.json", "devices.json", "recorders.json"))
    raw_settings=parsed["settings.json"]
    if not isinstance(raw_settings,dict):raise ValueError("Некорректные настройки backup")
    version=raw_settings.get("schema_version",0)
    if type(version) is not int or version not in (0,1,2,3):raise ValueError("Неизвестная версия данных backup")
    modern=version==3
    for name, values, maximum in [("Пользователи", users, 1000), ("Группы", groups, 1000), ("Камеры", cameras, 4096), ("Регистраторы", recorders, 4096)]:
        if not isinstance(values, list) or len(values) > maximum or any(not isinstance(item, dict) for item in values):
            raise ValueError(name + ": неверный формат backup")

    group_ids = [group.get("id") for group in groups]
    camera_ids = [cam.get("id") for cam in cameras]
    ids(group_ids); ids(camera_ids)
    if len(set(group_ids)) != len(group_ids) or len(set(camera_ids)) != len(camera_ids):
        raise ValueError("В backup повторяются идентификаторы")
    clean_groups = schema.spaces(groups,set(camera_ids),modern)

    clean_users = []
    for user in users:
        name = text(user.get("username"), "Логин", 64, True)
        if not LOGIN_RE.fullmatch(name) or not isinstance(user.get("role"), str) or user.get("role") not in {"admin", "viewer"}: raise ValueError("Неверный пользователь backup")
        digest = user.get("password_hash", "")
        if not isinstance(digest, str) or len(digest) > 512: raise ValueError("Неверный хеш пароля")
        parts = digest.split("$")
        pending=modern and user.get("active") is False and user.get("role")=="viewer" and not digest
        if not pending and (len(parts) != 3 or not re.fullmatch(r"[A-Za-z0-9]{8,64}", parts[1]) or not re.fullmatch(r"[a-f0-9]{64,128}", parts[2])):
            raise ValueError("Неверный формат хеша пароля")
        method = parts[0].split(":")
        valid = pending
        if len(method) == 3 and method[:2] == ["pbkdf2", "sha256"]:
            valid = method[2].isdigit() and 10000 <= int(method[2]) <= 5_000_000
        if len(method) == 4 and method[0] == "scrypt" and all(x.isdigit() for x in method[1:]):
            n, r, p = map(int, method[1:]); valid = n in {16384, 32768, 65536, 131072} and 1 <= r <= 16 and 1 <= p <= 4 and n * r <= 1_048_576
        if not valid: raise ValueError("Неподдерживаемые параметры хеша пароля")
        chosen = ids(user.get("group_ids", []))
        if not modern and set(chosen) - set(group_ids): raise ValueError("Пользователь ссылается на отсутствующую группу")
        access = user.get("group_access", {})
        if not isinstance(access, dict) or set(access) - set(chosen) or any(not isinstance(v, str) or v not in {"read", "edit"} for v in access.values()):
            raise ValueError("Некорректные права групп")
        if not isinstance(user.get("theme", "auto"), str) or user.get("theme", "auto") not in {"auto", "dark", "light"} or not isinstance(user.get("language", "ru"), str) or user.get("language", "ru") not in {"ru", "en"}:
            raise ValueError("Некорректный язык или тема")
        clean_users.append({"username": name, "alias": text(user.get("alias", name), "Псевдоним", 100),
                            "avatar": safe_image(user.get("avatar", "")), "role": user["role"], "password_hash": digest,
                            "theme": user.get("theme", "auto"), "language": user.get("language", "ru"),
                            "group_ids": chosen, "group_access": {gid: access.get(gid, "read") for gid in chosen},
                            "archive_access": user["role"] == "admin" or user.get("archive_access") is True})
        for key in ("grants","permissions","active","pending_grants"):
            if modern and key in user:clean_users[-1][key]=user[key]
        clean_users[-1]=schema.policy(clean_users[-1],reset_export=not modern)
    if not any(u["role"] == "admin" and u["active"] for u in clean_users) or len({u["username"].casefold() for u in clean_users}) != len(clean_users):
        raise ValueError("Backup должен содержать администратора и уникальные логины")

    clean_cameras = []
    def check_secret(encrypted):
        if not isinstance(encrypted,str):raise ValueError("Неверный пароль устройства в backup")
        if encrypted:
            try:
                if not encrypted.startswith("enc:"):raise ValueError()
                cipher.decrypt(encrypted[4:].encode()).decode("utf-8")
            except (InvalidToken,ValueError,UnicodeError):raise ValueError("Пароли устройств не соответствуют ключу backup") from None
    for cam in cameras:
        encrypted = cam.get("password", "")
        if not isinstance(encrypted, str): raise ValueError("Неверный пароль камеры в backup")
        if encrypted:
            try:
                if not isinstance(encrypted, str) or not encrypted.startswith("enc:"): raise ValueError()
                cipher.decrypt(encrypted[4:].encode()).decode("utf-8")
            except (InvalidToken, ValueError, UnicodeError): raise ValueError("Пароли камер не соответствуют ключу backup") from None
        clean_cameras.append(validate_device({k: v for k, v in cam.items() if k != "password"}, cam, SimpleNamespace(enc_pwd=lambda value: value)))
        for key in ("origin_id","import_id"):
            if key in cam:clean_cameras[-1][key]=schema.identifier(cam[key])
        if not isinstance(cam.get("is_hidden",False),bool):raise ValueError("Неверная видимость камеры")
        clean_cameras[-1]["visibility_revision"]=integer(cam.get("visibility_revision",0),"Ревизия видимости",0,10**16)
        if modern:clean_cameras[-1]["source_key"]=text(cam.get("source_key"),"Источник канала",600,True)
    clean_recorders = []
    for recorder in recorders:
        if not isinstance(recorder.get("id"), str) or not IDENTIFIER_RE.fullmatch(recorder["id"]): raise ValueError("Некорректный ID регистратора")
        physical = text(recorder.get("connection_key"), "Ключ подключения", 300, True)
        parts = physical.split("|")
        if len(parts) != 3 or parts[0] not in {"dvrip", "onvif"} or not re.fullmatch(r"[A-Za-z0-9_.:-]+", parts[1]) or ".." in parts[1]: raise ValueError("Неверный адрес регистратора")
        integer(parts[2], "Порт регистратора", 1, 65535)
        clean_recorders.append({"id": recorder["id"], "name": text(recorder.get("name"), "Имя регистратора", 150, True), "connection_key": physical})
        if modern:
            if recorder.get("kind") not in ("camera","recorder"):raise ValueError("Неверный тип устройства")
            connection=recorder.get("connection")
            if not isinstance(connection,dict) or set(connection)-set(CONNECTION_FIELDS):raise ValueError("Неверные параметры устройства")
            check_secret(connection.get("password",""))
            validated=validate_device({**{k:v for k,v in connection.items() if k!="password"},"id":recorder["id"],"name":recorder["name"]},connection,SimpleNamespace(enc_pwd=lambda value:value))
            if DataStore.connection_key(validated)!=physical:raise ValueError("Адрес устройства не соответствует ключу")
            clean_recorders[-1].update(kind=recorder["kind"],connection={k:validated[k] for k in connection if k in validated})
            if recorder.get("connection_mode"):
                if recorder["connection_mode"] not in ("dvrip","onvif","rtsp"):raise ValueError("Неверный метод подключения")
                clean_recorders[-1]["connection_mode"]=recorder["connection_mode"]
            for key in ("origin_id","import_id"):
                if key in recorder:clean_recorders[-1][key]=schema.identifier(recorder[key])
    if len({r["id"] for r in clean_recorders}) != len(clean_recorders) or (not modern and len({r["connection_key"] for r in clean_recorders}) != len(clean_recorders)):
        raise ValueError("В backup повторяются регистраторы")
    by_key = {r["connection_key"]: r for r in clean_recorders}
    for cam in clean_cameras:
        physical = DataStore.connection_key(cam)
        if modern:
            if cam.get("recorder_id") not in {r["id"] for r in clean_recorders}:raise ValueError("Камера ссылается на отсутствующее устройство")
            continue
        if physical not in by_key:
            item = {"id": "rec_" + hashlib.sha256(physical.encode()).hexdigest()[:24], "name": "Регистратор " + str(len(by_key) + 1), "connection_key": physical}
            by_key[physical] = item; clean_recorders.append(item)
        cam["recorder_id"] = by_key[physical]["id"]
    if len({r["id"] for r in clean_recorders}) != len(clean_recorders): raise ValueError("Конфликт ID регистратора")
    clean_cameras,clean_recorders=physical_catalog(clean_cameras,clean_recorders,DataStore.connection_key)
    if modern and any(r["kind"]=="camera" and len({c["source_key"] for c in clean_cameras if c["recorder_id"]==r["id"]})>1 for r in clean_recorders):
        raise ValueError("У отдельной IP-камеры один аппаратный источник")
    clean_groups=normalize_spaces(clean_groups,clean_cameras)

    raw_settings = parsed["settings.json"]
    if not isinstance(raw_settings, dict): raise ValueError("Некорректные настройки backup")
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["schema_version"]=3
    settings["catalog_origin"]=schema.identifier(raw_settings["catalog_origin"]) if raw_settings.get("catalog_origin") else uuid.uuid4().hex
    for item in clean_cameras+clean_recorders:item.setdefault("origin_id",settings["catalog_origin"])
    for key, allowed in {"language": {"ru", "en"}, "snapshot_format": {"jpeg", "png", "webp"}, "archive_format": {"mp4"}}.items():
        value = raw_settings.get(key, settings[key])
        if not isinstance(value, str) or value not in allowed: raise ValueError("Неизвестный параметр backup: " + key)
        settings[key] = value
    try: ZoneInfo(raw_settings.get("timezone", settings["timezone"]))
    except (ZoneInfoNotFoundError, TypeError, ValueError): raise ValueError("Неверный часовой пояс") from None
    settings["timezone"] = raw_settings.get("timezone", settings["timezone"])
    brand = raw_settings.get("branding", {})
    if not isinstance(brand, dict): raise ValueError("Неверное оформление backup")
    settings["branding"].update({k: text(brand.get(k, settings["branding"][k]), k, 80, k == "name") for k in ("name", "subtitle")})
    for k in ("logo", "favicon"): settings["branding"][k] = safe_image(brand.get(k, ""))
    for k in ("logo_icon","favicon_icon"):
        value=brand.get(k,"")
        if not isinstance(value,str):raise ValueError("Некорректное имя значка")
        settings["branding"][k]="" if value=="" else schema.icon(value)
    color = brand.get("accent", settings["branding"]["accent"])
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color): raise ValueError("Неверный цвет backup")
    settings["branding"]["accent"] = color
    icon_color=brand.get("icon_color",settings["branding"]["icon_color"])
    if not isinstance(icon_color,str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",icon_color):raise ValueError("Неверный цвет значков")
    settings["branding"]["icon_color"]=icon_color
    for k in ("motion", "show_clock"):
        if not isinstance(brand.get(k, settings["branding"][k]), bool): raise ValueError("Неверный параметр оформления")
        settings["branding"][k] = brand.get(k, settings["branding"][k])
    for k, allowed in {"recorder_labels": {"ip", "name"}, "density": {"compact", "comfortable"}, "corners": {"rounded", "square"}}.items():
        value = brand.get(k, settings["branding"][k])
        if not isinstance(value, str) or value not in allowed: raise ValueError("Неверный вариант оформления")
        settings["branding"][k] = value
    settings["branding"]["wall_gap"] = integer(brand.get("wall_gap", 3), "Отступ", 0, 12)
    resource = raw_settings.get("resources", {})
    if not isinstance(resource, dict) or not isinstance(resource.get("profile", "standard"), str) or resource.get("profile", "standard") not in {"standard", "maximum", "custom"}: raise ValueError("Неверный профиль ресурсов")
    for k, bounds in {"max_live_streams": (1, 128), "max_archive_streams": (1, 16), "archive_buffer_mb": (2, 128), "archive_idle_seconds": (30, 600), "ffmpeg_threads": (0, 32)}.items():
        settings["resources"][k] = integer(resource.get(k, settings["resources"][k]), k, *bounds)
    settings["resources"]["profile"] = resource.get("profile", "standard")
    diagnostic = raw_settings.get("diagnostics", {})
    if not isinstance(diagnostic, dict) or not isinstance(diagnostic.get("enabled", True), bool): raise ValueError("Неверные настройки диагностики")
    settings["diagnostics"]["enabled"] = diagnostic.get("enabled", True)
    settings["auth_epoch"] = uuid.uuid4().hex
    normalized = {"users.json": clean_users, "groups.json": clean_groups, "devices.json": clean_cameras,
                  "recorders.json": clean_recorders, "settings.json": settings}
    result = {name: json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8") for name, value in normalized.items()}
    result.update({".camkey": camera_key, ".flask_secret": secret.encode()})
    summary = {"users": len(users), "groups": len(groups), "cameras": len(cameras), "recorders": len(clean_recorders),
               "admins": [u["username"] for u in clean_users if u["role"] == "admin"], "sha256": hashlib.sha256(raw).hexdigest()}
    return result, summary
