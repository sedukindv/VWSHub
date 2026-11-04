"""Content-addressed raster assets, shared by uploads, migration and backups."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import zipfile

IMAGE_NAME = re.compile(r"[a-f0-9]{64}\.(?:png|jpeg|webp)\Z")
PREFIX = "/images/"


def image_name(value):
    if isinstance(value, str) and value.startswith(PREFIX) and IMAGE_NAME.fullmatch(value[len(PREFIX):]):
        return value[len(PREFIX):]
    return None


def image_file(name):
    return isinstance(name, str) and name.startswith("images/") and bool(IMAGE_NAME.fullmatch(name[7:]))


def decode_image(value):
    from .store import safe_image
    safe_image(value,max_bytes=524288)
    metadata, encoded = value.split(",", 1)
    extension = metadata.split("/", 1)[1].split(";", 1)[0]
    raw = base64.b64decode(encoded, validate=True)
    return hashlib.sha256(raw).hexdigest() + "." + extension, raw


def validate_asset(name, raw):
    if not IMAGE_NAME.fullmatch(name) or len(raw) > 524288:
        raise ValueError("Неверное изображение backup")
    extension = name.rsplit(".", 1)[1]
    actual, _ = decode_image("data:image/" + extension + ";base64," + base64.b64encode(raw).decode())
    if actual != name:
        raise ValueError("Контрольная сумма изображения не совпадает")


def prepare_restore_images(files):
    """Normalize legacy inline assets in memory before the restore journal starts."""
    result=dict(files)
    settings=json.loads(result["settings.json"])
    users=json.loads(result["users.json"])
    if not isinstance(settings,dict) or not isinstance(settings.get("branding",{}),dict) or not isinstance(users,list) or any(not isinstance(user,dict) for user in users):
        raise ValueError("Некорректные JSON или ключи backup")
    for name,raw in result.items():
        if image_file(name):validate_asset(name[7:],raw)
    changed=False
    def prepare(value):
        nonlocal changed
        if not value:return ""
        name=image_name(value)
        if not name:
            name,raw=decode_image(value)
            result["images/"+name]=raw
            changed=True
        if "images/"+name not in result:
            raise ValueError("Backup не содержит используемое изображение")
        return PREFIX+name
    brand=settings.setdefault("branding",{})
    for key in ("logo","favicon"):brand[key]=prepare(brand.get(key,""))
    for user in users:user["avatar"]=prepare(user.get("avatar",""))
    if changed:
        result["settings.json"]=json.dumps(settings,ensure_ascii=False,allow_nan=False).encode("utf-8")
        result["users.json"]=json.dumps(users,ensure_ascii=False,allow_nan=False).encode("utf-8")
    return result


class Images:
    def __init__(self, store):
        self.store = store
        self.directory = store.base_dir / "images"
        self.directory.mkdir(exist_ok=True)
        if self.directory.resolve() != self.directory or self.directory.is_symlink():
            raise ValueError("Каталог изображений не должен быть ссылкой")
        from .store import protected
        protected(self.directory, directory=True)

    def path(self, name):
        if not isinstance(name, str) or not IMAGE_NAME.fullmatch(name):
            raise ValueError("Неверное имя изображения")
        target = self.directory / name
        if target.is_symlink() or target.resolve().parent != self.directory:
            raise ValueError("Небезопасный путь изображения")
        return target

    def persist(self, value):
        if not value:
            return ""
        name = image_name(value)
        if name:
            target = self.path(name)
            if not target.is_file() or target.stat().st_size>524288:
                raise ValueError("Изображение не найдено")
            validate_asset(name, target.read_bytes())
            return value
        name, raw = decode_image(value)
        target = self.path(name)
        if target.exists() and not target.is_file():raise ValueError("Неверный файл изображения")
        if not target.exists() or target.stat().st_size!=len(raw) or target.read_bytes()!=raw:
            self.store._write_bytes(target, raw)
        return PREFIX + name

    def referenced(self, settings=None, users=None):
        settings = settings if settings is not None else self.store.get_settings()
        users = users if users is not None else self.store.get_users()
        values = [settings.get("branding", {}).get(key, "") for key in ("logo", "favicon")]
        values += [user.get("avatar", "") for user in users]
        return {name for value in values if (name := image_name(value))}

    def iter_backup_files(self):
        for name in sorted(self.referenced()):
            target=self.path(name)
            if not target.is_file() or target.stat().st_size>524288:raise ValueError("Неверное изображение в каталоге")
            raw=target.read_bytes();validate_asset(name,raw)
            yield "images/"+name,raw

    def backup_files(self):
        return dict(self.iter_backup_files())

    def snapshot(self,label,folder_name="migration-backups"):
        if label not in {"images","wvw-brand","restore"} or folder_name not in {"migration-backups","restore-backups"}:raise ValueError("Неверный тип копии")
        folder=self.store.base_dir/folder_name;folder.mkdir(exist_ok=True)
        if folder.resolve()!=folder:raise ValueError("Небезопасный каталог копий")
        from .store import protected
        protected(folder,directory=True)
        snapshot=folder/("before-"+label+"-"+str(time.time_ns())+".zip")
        temporary=snapshot.with_suffix(".zip.tmp")
        try:
            with zipfile.ZipFile(temporary,"x",zipfile.ZIP_DEFLATED) as archive:
                protected(temporary)
                for name in ("users.json","groups.json","devices.json","recorders.json","settings.json",".camkey",".flask_secret"):
                    archive.writestr("data/"+name,(self.store.base_dir/name).read_bytes())
                for name,raw in self.iter_backup_files():archive.writestr("data/"+name,raw)
            os.replace(temporary,snapshot);protected(snapshot)
        finally:
            if temporary.exists():temporary.unlink()
        return snapshot

    def migrate(self):
        settings, users = self.store.get_settings(), self.store.get_users()
        values = [settings["branding"].get(key, "") for key in ("logo", "favicon")]
        values += [user.get("avatar", "") for user in users]
        if not any(isinstance(value, str) and value.startswith("data:") for value in values):
            return
        # Validate all source values before creating a snapshot or changing JSON.
        for value in values:
            if value and not image_name(value):
                decode_image(value)
        self.snapshot("images")
        for key in ("logo", "favicon"):
            settings["branding"][key] = self.persist(settings["branding"].get(key, ""))
        for user in users:
            user["avatar"] = self.persist(user.get("avatar", ""))
        self.store.transaction({"settings.json": json.dumps(settings, ensure_ascii=False).encode(),
                                "users.json": json.dumps(users, ensure_ascii=False).encode()})

    def collect(self):
        """A grace period protects recent uploads; never follow links."""
        keep, cutoff = self.referenced(), time.time() - 86400
        try:targets=list(self.directory.iterdir())
        except OSError:return
        for target in targets:
            if IMAGE_NAME.fullmatch(target.name) and target.name not in keep:
                try:
                    target = self.path(target.name)
                    if target.is_file() and target.stat().st_mtime < cutoff:
                        target.unlink()
                except (OSError, ValueError):
                    pass
