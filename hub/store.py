"""Protected JSON data, atomic replacement and non-destructive legacy migration."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import generate_password_hash

DEFAULT_SETTINGS = {
    "branding": {"name":"VWSHub", "subtitle":"Video workspace", "logo":"", "favicon":"", "logo_icon":"", "favicon_icon":"", "accent":"#526cf5", "motion":True,
                 "recorder_labels":"ip", "density":"comfortable", "corners":"rounded", "show_clock":True, "wall_gap":3,
                 "icon_color":"#71809c"},
    "diagnostics":{"enabled":True},
    "timezone":"Asia/Omsk", "language":"ru", "snapshot_format":"jpeg", "archive_format":"mp4",
    "resources": {"profile":"standard", "max_live_streams":16, "max_archive_streams":4,
                  "archive_buffer_mb":16, "archive_idle_seconds":180, "ffmpeg_threads":2},
}

class DataCorruptError(RuntimeError):
    pass

def protected(path: Path, directory=False):
    try: os.chmod(path, 0o700 if directory else 0o600)
    except OSError: pass

class DataLock:
    """Reentrant per-thread lock backed by an OS lock across server workers."""
    def __init__(self,path):
        self.path=Path(path);self.thread_lock=threading.RLock();self.local=threading.local()
        with self.path.open("ab") as handle:
            if handle.tell()==0:handle.write(b"0")
        protected(self.path)
    def __enter__(self):
        self.thread_lock.acquire()
        depth=getattr(self.local,"depth",0)
        if depth==0:
            handle=self.path.open("r+b")
            try:
                if os.name=="nt":
                    import msvcrt
                    handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            except Exception:
                handle.close();self.thread_lock.release();raise
            self.local.handle=handle
        self.local.depth=depth+1
        return self
    def __exit__(self,*ignored):
        self.local.depth-=1
        try:
            if self.local.depth==0:
                handle=self.local.handle
                try:
                    if os.name=="nt":
                        import msvcrt
                        handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
                finally:handle.close();del self.local.handle
        finally:self.thread_lock.release()

def safe_image(value, max_bytes=262144):
    if not value: return ""
    if not isinstance(value, str): raise ValueError("Изображение должно быть строкой data URL")
    match=re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)",value)
    if not match or len(match[2])>max_bytes*4//3+8: raise ValueError("Изображение: PNG/JPEG/WebP до 256 КБ")
    try: raw=base64.b64decode(match[2],validate=True)
    except Exception: raise ValueError("Некорректное изображение") from None
    valid=(match[1]=="png" and raw.startswith(b"\x89PNG\r\n\x1a\n") or
           match[1]=="jpeg" and raw.startswith(b"\xff\xd8\xff") or
           match[1]=="webp" and raw.startswith(b"RIFF") and raw[8:12]==b"WEBP")
    if not valid or not raw or len(raw)>max_bytes: raise ValueError("Некорректное растровое изображение")
    return value

class DataStore:
    def __init__(self, base_dir, legacy_dir=None):
        self.base_dir=Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True,exist_ok=True)
        protected(self.base_dir,True)
        self._cache={};self.revision=0
        self.lock=DataLock(self.base_dir/".store.lock")
        with self.lock:self._initialize(legacy_dir)

    def _initialize(self,legacy_dir):
        self._recover_restore()
        self.users_file=self.base_dir/"users.json"
        self.devices_file=self.base_dir/"devices.json"
        self.cameras_file=self.devices_file
        self.groups_file=self.base_dir/"groups.json"
        self.settings_file=self.base_dir/"settings.json"
        self.recorders_file=self.base_dir/"recorders.json"
        self.audit_file=self.base_dir/"audit.jsonl"
        self._migrate(Path(legacy_dir).resolve() if legacy_dir else self.base_dir.parent)
        if self.settings_file.exists():
            existing_settings=self._read(self.settings_file)
            if not isinstance(existing_settings,dict):raise DataCorruptError("Неверный формат settings.json; исходник не перезаписан")
            schema_version=existing_settings.get("schema_version",0)
            if type(schema_version) is not int or schema_version not in (0,1,2,3):
                raise DataCorruptError("Неизвестная версия данных. Используйте совместимую версию VWSHub; исходные данные не изменены")
        self.key_file=self.base_dir/".camkey"
        if not self.key_file.exists():
            encrypted_sources=self.devices_file.exists() and any(str(d.get("password","")).startswith("enc:") for d in self._read(self.devices_file) if isinstance(d,dict))
            encrypted_parents=self.recorders_file.exists() and any(str(d.get("connection",{}).get("password","")).startswith("enc:") for d in self._read(self.recorders_file) if isinstance(d,dict))
            if encrypted_sources or encrypted_parents:
                raise DataCorruptError("Найдены зашифрованные пароли устройств. Перенесите исходный .camkey в data/; новый ключ не создан")
            self._write_bytes(self.key_file,Fernet.generate_key())
        self.fernet=Fernet(self.key_file.read_bytes().strip())
        self.secret_file=self.base_dir/".flask_secret"
        if not self.secret_file.exists(): self._write_bytes(self.secret_file,(uuid.uuid4().hex+uuid.uuid4().hex).encode())
        for path,default in [(self.users_file,[]),(self.devices_file,[]),(self.groups_file,[]),(self.recorders_file,[])]:
            if not path.exists(): self._write(path,default)
            elif not isinstance(self._read(path),list): raise DataCorruptError(f"Неверный формат {path.name}; исходник не перезаписан")
        if not self.settings_file.exists(): self._write(self.settings_file,copy.deepcopy(DEFAULT_SETTINGS))
        self._normalize_legacy()
        from .structure import initialize_catalog
        initialize_catalog(self)
        self.save_devices(self.get_devices())

    @staticmethod
    def connection_key(device):
        return "|".join([str(device.get("protocol","dvrip")),str(device.get("ip","")).lower(),str(device.get("port",34567 if device.get("protocol","dvrip")=="dvrip" else 80))])

    def catalog_values(self,devices,recorder_names=None):
        from .structure import physical_catalog
        cameras,physical=physical_catalog(devices,self._read(self.recorders_file),self.connection_key,recorder_names)
        origin=self.get_settings().get("catalog_origin")
        if origin:
            for item in cameras+physical:item.setdefault("origin_id",origin)
        return cameras,physical

    def _reconcile_recorders(self,devices):
        devices,recorders=self.catalog_values(devices)
        if recorders!=self._read(self.recorders_file):self._write(self.recorders_file,recorders)
        return devices

    def _recover_restore(self):
        journal=self.base_dir/".restore-journal.json"
        if not journal.exists():return
        try:
            previous=json.loads(journal.read_text(encoding="utf-8"))
            allowed={"users.json","groups.json","devices.json","settings.json","recorders.json",".camkey",".flask_secret"}
            if not isinstance(previous,dict) or set(previous)-allowed:raise ValueError()
            for filename,encoded in previous.items():
                if encoded is None:
                    target=self.base_dir/filename
                    if target.exists():target.unlink()
                else:self._write_bytes(self.base_dir/filename,base64.b64decode(encoded,validate=True))
            journal.unlink()
        except Exception as exc:raise DataCorruptError("Не удалось восстановить прерванную транзакцию backup. Сохраните data и проверьте журнал восстановления") from exc

    def restore(self,files):
        allowed={"users.json","groups.json","devices.json","settings.json","recorders.json",".camkey",".flask_secret"}
        if set(files)!=allowed:raise ValueError("Неполный набор файлов восстановления")
        self.transaction(files)

    def transaction(self,files):
        """Readers see a whole catalog; a crash rolls back the incomplete journal."""
        allowed={"users.json","groups.json","devices.json","settings.json","recorders.json",".camkey",".flask_secret"}
        if not files or set(files)-allowed:raise ValueError("Неизвестные файлы транзакции")
        with self.lock:
            old={name:base64.b64encode((self.base_dir/name).read_bytes()).decode() if (self.base_dir/name).exists() else None for name in files}
            journal=self.base_dir/".restore-journal.json"
            self._write(journal,old)
            try:
                for name,content in files.items():self._write_bytes(self.base_dir/name,content)
                self.fernet=Fernet((self.base_dir/".camkey").read_bytes().strip())
                self._cache.clear();journal.unlink()
            except Exception:
                self._recover_restore();self.fernet=Fernet((self.base_dir/".camkey").read_bytes().strip());raise

    def save_catalog(self,devices,groups,recorder_names=None):
        with self.lock:
            from .structure import normalize_spaces
            devices,recorders=self.catalog_values(devices,recorder_names)
            groups=normalize_spaces(groups,devices)
            payload={"devices.json":devices,"groups.json":groups,"recorders.json":recorders}
            valid={"channels":{c["id"] for c in devices},"devices":{d["id"] for d in recorders},
                   "spaces":{s["id"] for s in groups},"zones":{z["id"] for s in groups for z in s.get("zones",[])}}
            users=self.get_users();changed=False
            for user in users:
                for kind,known in valid.items():
                    grants=user.get("grants",{}).get(kind,{})
                    for resource_id in set(grants)-known:grants.pop(resource_id);changed=True
            if changed:
                from .access import normalize_user
                payload["users.json"]=[normalize_user(u) for u in users]
            self.transaction({name:json.dumps(value,ensure_ascii=False,allow_nan=False).encode("utf-8") for name,value in payload.items()})

    def _migrate(self, legacy):
        roots=list(dict.fromkeys([self.base_dir,legacy]))
        combined={}
        for root in roots:
            old=root/"vms_data.json"
            if old.exists():
                value=self._read(old)
                if isinstance(value,dict): combined=value; break
        for target,names,key in [(self.users_file,["users.json"],"users"),(self.devices_file,["devices.json","camconfig.json"],"cameras"),(self.groups_file,["groups.json"],"groups")]:
            if target.exists(): continue
            source=next((root/name for root in roots for name in names if (root/name).exists() and root/name!=target),None)
            if source:
                value=self._read(source)
                if not isinstance(value,list): raise DataCorruptError(f"Неверный формат {source.name}; миграция остановлена")
                self._write(target,value)
            elif key in combined: self._write(target,combined[key])
        # Copy keys before touching encrypted passwords. Never rotate an existing key.
        for name in (".camkey",".flask_secret"):
            target=self.base_dir/name
            if target.exists(): continue
            source=legacy/name
            if source.exists() and source!=target: self._write_bytes(target,source.read_bytes())
        settings=legacy/"settings.json"
        if not self.settings_file.exists() and settings.exists() and settings!=self.settings_file:
            value=self._read(settings)
            if isinstance(value,dict): self._write(self.settings_file,value)
        branding=legacy/"branding.json"
        if not self.settings_file.exists() and branding.exists():
            value=self._read(branding)
            if isinstance(value,dict):
                settings=copy.deepcopy(DEFAULT_SETTINGS);brand=settings["branding"]
                name=str(value.get("site_name") or "").strip()
                if name and name not in {"Web VMS","WebVMS"}:brand["name"]=name[:80]
                brand["subtitle"]=str(value.get("tagline") or brand["subtitle"])[:80]
                if re.fullmatch(r"#[0-9A-Fa-f]{6}",str(value.get("accent",""))):brand["accent"]=value["accent"]
                for old,new in (("logo_data","logo"),("favicon_data","favicon")):
                    try:brand[new]=safe_image(value.get(old,""),max_bytes=524288)
                    except ValueError:pass
                brand["motion"]=value.get("animations_enabled") is not False
                self._write(self.settings_file,settings)

    def _normalize_legacy(self):
        with self.lock:
            devices=self.get_devices(); changed=False
            for device in devices:
                if not isinstance(device,dict): raise DataCorruptError("Неверная запись devices.json")
                password=device.get("password","")
                if password and not str(password).startswith("enc:"):
                    device["password"]=self.enc_pwd(str(password));changed=True
            if changed:self.save_devices(devices)
            users=self.get_users();changed=False
            for user in users:
                if not isinstance(user,dict): raise DataCorruptError("Неверная запись users.json")
                original=dict(user)
                user.setdefault("username",str(user.get("login") or ""))
                user.setdefault("alias",user["username"])
                user.setdefault("avatar","")
                user.setdefault("theme","auto")
                user.setdefault("language","ru")
                user.setdefault("group_ids",user.get("allowed_group_ids",[]))
                user.setdefault("archive_access",bool(user.get("can_access_archive",user.get("role")=="admin")))
                if "password" in user:
                    user.setdefault("password_hash",generate_password_hash(str(user.pop("password"))))
                changed|=original!=user
            if changed:self.save_users(users)

    def _read(self,path):
        try:
            path=Path(path);stamp=path.stat();signature=(stamp.st_mtime_ns,stamp.st_size,stamp.st_ino)
            cached=self._cache.get(str(path))
            if cached and cached[0]==signature:return copy.deepcopy(cached[1])
            with path.open("r",encoding="utf-8-sig") as source:value=json.load(source)
            self._cache[str(path)]=(signature,value)
            return copy.deepcopy(value)
        except (ValueError,OSError) as exc:raise DataCorruptError(f"Не удалось прочитать {Path(path).name}; данные не изменены") from exc

    def _write_bytes(self,path,content):
        path=Path(path);temporary=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
        try:
            with temporary.open("xb") as stream:
                protected(temporary);stream.write(content);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path);protected(path)
            self._cache.pop(str(path),None)
            if path.name in {"users.json","devices.json","recorders.json","groups.json","settings.json"}:self.revision+=1
        finally:
            if temporary.exists():temporary.unlink()

    def _write(self,path,value):
        self._write_bytes(path,json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode("utf-8"))

    def get_users(self):
        with self.lock:return self._read(self.users_file)
    def get_devices(self):
        with self.lock:return self._read(self.devices_file)
    get_cameras=get_devices
    def get_groups(self):
        with self.lock:return self._read(self.groups_file)
    def get_recorders(self):
        with self.lock:return self._read(self.recorders_file)
    def get_settings(self):
        with self.lock:
            raw=self._read(self.settings_file)
            if not isinstance(raw,dict):raise DataCorruptError("Неверный формат settings.json")
            result=copy.deepcopy(DEFAULT_SETTINGS);result.update(raw)
            result["branding"]={**DEFAULT_SETTINGS["branding"],**(raw.get("branding") or {})}
            result["resources"]={**DEFAULT_SETTINGS["resources"],**(raw.get("resources") or {})}
            result["diagnostics"]={**DEFAULT_SETTINGS["diagnostics"],**(raw.get("diagnostics") or {})}
            return result
    def save_users(self,value):
        from .access import normalize_user
        with self.lock:self._write(self.users_file,[normalize_user(user) for user in value])
    def save_devices(self,value):
        with self.lock:
            devices,recorders=self.catalog_values(value)
            self.transaction({name:json.dumps(data,ensure_ascii=False,allow_nan=False).encode("utf-8") for name,data in
                              {"devices.json":devices,"recorders.json":recorders}.items()})
    save_cameras=save_devices
    def save_groups(self,value):
        from .structure import normalize_spaces
        with self.lock:self._write(self.groups_file,normalize_spaces(value,self.get_devices()))
    def save_settings(self,value):
        with self.lock:self._write(self.settings_file,value)
    def save_recorders(self,value):
        with self.lock:self._write(self.recorders_file,value)
    def enc_pwd(self,value):return "enc:"+self.fernet.encrypt(value.encode()).decode() if value else ""
    def dec_pwd(self,value):
        if not value:return ""
        if not str(value).startswith("enc:"):return str(value)
        try:return self.fernet.decrypt(str(value)[4:].encode()).decode()
        except InvalidToken:raise RuntimeError("Пароль устройства не расшифрован: восстановите исходный .camkey") from None
    def secret(self):return self.secret_file.read_text(encoding="utf-8").strip()

    def audit(self,actor,action,detail=None):
        def clean(value):
            if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items() if not re.search(r"password|passwd|secret|credential|token|key",str(k),re.I)}
            if isinstance(value,list):return [clean(v) for v in value[:100]]
            if isinstance(value,str):return re.sub(r"(\w+://)[^\s/@]+:[^\s/@]+@",r"\1[redacted]@",value)[:1500]
            return value
        entry={"time":datetime.now(timezone.utc).isoformat(timespec="seconds"),"actor":str(actor or "system"),"action":str(action),"detail":clean(detail or {})}
        with self.lock:
            if self.audit_file.exists() and self.audit_file.stat().st_size>2_000_000:
                for index in (2,1):
                    old=self.audit_file.with_suffix(f".jsonl.{index}")
                    if old.exists():os.replace(old,self.audit_file.with_suffix(f".jsonl.{index+1}"))
                os.replace(self.audit_file,self.audit_file.with_suffix(".jsonl.1"))
            with self.audit_file.open("a",encoding="utf-8") as target:target.write(json.dumps(entry,ensure_ascii=False)+"\n")
            protected(self.audit_file)
    def logs(self,limit=200):
        with self.lock:
            if not self.audit_file.exists():return []
            result=[]
            for line in self.audit_file.read_text(encoding="utf-8").splitlines()[-limit:]:
                try:result.append(json.loads(line))
                except ValueError:continue
            return list(reversed(result))
