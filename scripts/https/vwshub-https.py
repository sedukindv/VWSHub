#!/usr/bin/env python3
"""VWSHub HTTPS Installer — local CA and existing Debian/Ubuntu reverse proxy.

Managed by VWSHub HTTPS Installer. No product data or media configuration is read
or changed. Test code injects a filesystem root and command runner; the CLI never
exposes a sandbox bypass and refuses execution outside Linux/root.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import fnmatch
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time

MARKER = "Managed by VWSHub HTTPS Installer"
SERVICE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*\.service\Z")
USERNAME = re.compile(r"[a-z_][a-z0-9_-]*[$]?\Z", re.I)


class SetupError(RuntimeError):
    pass


def identities(dns="", ip=""):
    dns = dns.strip().rstrip(".").lower()
    if dns:
        try:
            dns = dns.encode("idna").decode("ascii")
        except UnicodeError:
            raise SetupError("Invalid DNS name") from None
        if len(dns) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p) for p in dns.split(".")):
            raise SetupError("Invalid DNS name")
        try:
            ipaddress.ip_address(dns)
        except ValueError:
            pass
        else:
            raise SetupError("Use --ip-address for an IP SAN, not --dns-name")
    if ip:
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            raise SetupError("Invalid IPv4 address") from None
        if parsed.version != 4 or parsed.is_unspecified or parsed.is_multicast:
            raise SetupError("A unicast IPv4 address is required")
        ip = str(parsed)
    if not dns and not ip:
        raise SetupError("Provide DNS, IPv4, or both")
    return dns, ip


def execute(args, check=True, input=None):
    result = subprocess.run([str(a) for a in args], input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise SetupError(f"{Path(str(args[0])).name} failed: " + result.stderr.decode(errors="replace")[-1600:])
    return result


class Transaction:
    """Back up every touched file/symlink before changing it, including modes."""
    def __init__(self, owner):
        self.owner, self.records = owner, []
        self.directory = owner.base / "backups" / str(time.time_ns())
        self.directory.mkdir(parents=True, mode=0o700)
        os.chmod(self.directory, 0o700)

    def remember(self, path):
        path = Path(path)
        if any(r["path"] == str(path) for r in self.records):
            return
        record = {"path": str(path), "exists": path.exists() or path.is_symlink()}
        if path.is_symlink():
            record["link"] = os.readlink(path)
        elif path.exists():
            if not path.is_file():
                raise SetupError("Refusing to replace non-file: " + str(path))
            record.update(data=base64.b64encode(path.read_bytes()).decode(), mode=path.stat().st_mode & 0o777)
        self.records.append(record)
        self.owner.atomic(self.directory / "journal.json", json.dumps(self.records).encode(), 0o600)

    def write(self, path, data, mode=0o644, managed=True):
        path = Path(path)
        if path.is_symlink():
            raise SetupError("Refusing to overwrite a symlink: " + str(path))
        if managed and path.exists() and MARKER not in path.read_text():
            raise SetupError("Foreign file, left untouched: " + str(path))
        self.remember(path)
        self.owner.atomic(path, data.encode() if isinstance(data, str) else data, mode)

    def link(self, path, target):
        path = Path(path)
        if path.exists() or path.is_symlink():
            if path.is_symlink() and os.readlink(path) == str(target):
                return
            raise SetupError("Foreign/conflicting link, left untouched: " + str(path))
        self.remember(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)

    def remove(self, path):
        path = Path(path)
        if path.exists() or path.is_symlink():
            self.remember(path)
            path.unlink()

    def rollback(self):
        for record in reversed(self.records):
            path = Path(record["path"])
            if path.is_symlink() or path.exists():
                path.unlink()
            if "link" in record:
                path.symlink_to(record["link"])
            elif "data" in record:
                self.owner.atomic(path, base64.b64decode(record["data"]), record["mode"])


class Installer:
    def __init__(self, root=Path("/"), run=execute, which=shutil.which, openssl=None, pause=time.sleep):
        self.root, self.run, self.which = Path(root), run, which
        self.base = self.path("/etc/vwshub/https")
        self.pki = self.path("/etc/vwshub/pki")
        self.package = self.path("/root/vwshub-https-client-package")
        self.state_path = self.base / "state.json"
        self.openssl = openssl or which("openssl") or "openssl"
        self.app_user = ""
        self.pause = pause

    def path(self, value):
        return self.root / value.lstrip("/")

    def atomic(self, path, data, mode=0o600):
        path = Path(path)
        for parent in path.parents:
            if parent == self.root:
                break
            if parent.is_symlink():
                raise SetupError("Refusing write through a directory symlink: " + str(parent))
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise SetupError("Refusing symlink write: " + str(path))
        temporary = path.with_name(path.name + "." + str(time.time_ns()) + ".tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def command(self, *args, check=True, input=None):
        return self.run(list(args), check=check, input=input)

    def ssl(self, *args, **kwargs):
        return self.command(self.openssl, *args, **kwargs)

    def prepare(self):
        if self.path("/etc/vwshub").is_symlink():
            raise SetupError("Managed parent directory must not be a symlink")
        for directory in (self.base, self.pki):
            if directory.is_symlink():
                raise SetupError("Managed directory must not be a symlink")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                if directory.stat().st_uid != 0 or directory.parent.stat().st_uid != 0 or directory.parent.stat().st_mode & 0o022:
                    raise SetupError("Managed directories and their parent must be root-owned and not group/world writable")

    def load(self):
        if not self.state_path.is_file() or self.state_path.is_symlink():
            raise SetupError("Not installed; run install first")
        state = json.loads(self.state_path.read_text())
        identities(state["dns"], state["ip"])
        if state.get("proxy") not in ("apache", "nginx") or not SERVICE.fullmatch(state.get("app_service", "")):
            raise SetupError("Invalid installer state")
        return state

    def active(self, unit):
        return self.command("systemctl", "is-active", "--quiet", unit, check=False).returncode == 0

    def enabled(self, unit):
        return self.command("systemctl", "is-enabled", "--quiet", unit, check=False).returncode == 0

    def account(self, user):
        import pwd
        if not USERNAME.fullmatch(user):
            raise SetupError("Invalid application user")
        try:
            return pwd.getpwnam(user)
        except KeyError:
            raise SetupError("Application user does not exist") from None

    def app_prefix(self, user=None):
        user = self.app_user if user is None else user
        if not user:
            return ["systemctl"]
        account = self.account(user)
        runtime = f"/run/user/{account.pw_uid}"
        if not self.path(runtime + "/bus").exists():
            raise SetupError("User systemd bus is unavailable; the existing user service must be running")
        return ["runuser", "-u", user, "--", "env", "XDG_RUNTIME_DIR=" + runtime, "DBUS_SESSION_BUS_ADDRESS=unix:path=" + runtime + "/bus", "systemctl", "--user"]

    def app_action(self, action, service=None, check=True):
        return self.command(*self.app_prefix(), action, *([service] if service else []), check=check)

    def app_identity(self, service):
        # Hash unit definitions, including hooks/drop-ins, without logging their
        # potentially sensitive Environment values. This is captured BEFORE edits.
        content = self.command(*self.app_prefix(), "cat", "--no-pager", service).stdout
        if not content.strip():
            raise SetupError("Cannot record the verified application's systemd unit identity")
        return hashlib.sha256(content).hexdigest()

    def restore_app(self, service, directory, identity):
        if self.app_identity(service) != identity:
            raise SetupError("Application unit changed concurrently; refusing to start a different service definition")
        try:
            self.verify_app(service, directory)
        except SetupError:
            pid = self.command(*self.app_prefix(), "show", service, "--property=MainPID", "--value").stdout.decode().strip()
            if pid != "0":
                raise SetupError("Application PID is no longer the verified process; rollback did not touch it") from None
            listeners = self.command("ss", "-H", "-ltnp").stdout.decode()
            if re.search(r":5000\s", listeners):
                raise SetupError("Another process owns port 5000; rollback did not touch it")
            # The exact previously verified unit is down; starting this known
            # definition is safe and does not require a nonexistent live PID.
        self.app_action("restart", service)

    def app_dropin(self, state):
        if state.get("app_user"):
            home = self.account(state["app_user"]).pw_dir
            return self.path(home + "/.config/systemd/user/" + state["app_service"] + ".d/vwshub-https.conf")
        return self.path("/etc/systemd/system/" + state["app_service"] + ".d/vwshub-https.conf")

    def detect_proxy(self, requested=None):
        running = [p for p, unit in (("apache", "apache2"), ("nginx", "nginx")) if self.active(unit)]
        installed = [p for p, exe in (("apache", "apache2ctl"), ("nginx", "nginx")) if self.which(exe)]
        if len(running) > 1:
            raise SetupError("Both Apache and Nginx are active; resolve listeners explicitly before installation")
        if running:
            if requested and requested != running[0]:
                raise SetupError("An existing different reverse proxy is active; no second server will be installed")
            return running[0], False
        if requested:
            if installed and requested not in installed:
                raise SetupError("A different proxy is already installed; refusing a second server")
            return requested, requested not in installed
        if len(installed) > 1:
            raise SetupError("Both proxies are installed; choose --proxy apache or --proxy nginx")
        return (installed[0], False) if installed else ("apache", True)

    def verify_app(self, service=None, app_dir=None, app_user=None):
        candidates = [service] if service else ["vwshub.service", "wvw.service"]
        if service and not SERVICE.fullmatch(service):
            raise SetupError("Invalid systemd service name")
        users = [app_user] if app_user is not None else [self.app_user]
        # Existing README deployments use systemd --user. Discover only the user
        # that owns the real port-5000 listener; never enumerate/kill processes.
        if not app_user and not self.app_user and os.name == "posix":
            import pwd
            listeners = self.command("ss", "-H", "-ltnp").stdout.decode()
            for line in listeners.splitlines():
                if "127.0.0.1:5000 " not in line:
                    continue
                for pid in re.findall(r"pid=(\d+)", line):
                    try:
                        status = self.path(f"/proc/{pid}/status").read_text()
                        uid = int(re.search(r"(?m)^Uid:\s+\d+\s+(\d+)", status)[1])
                        user = pwd.getpwuid(uid).pw_name
                        if user not in users and self.path(f"/run/user/{uid}/bus").exists():
                            users.append(user)
                    except (OSError, TypeError, KeyError):
                        pass
        for user in users:
            for unit in candidates:
                answer = self.command(*self.app_prefix(user), "show", unit, "--property=MainPID", "--value", check=False)
                raw = answer.stdout.decode().strip()
                if not raw.isdigit() or int(raw) <= 1:
                    continue
                pid = int(raw)
                proc = self.path(f"/proc/{pid}")
                try:
                    command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode()
                    directory = (proc / "cwd").resolve(strict=True)
                except OSError:
                    continue
                if "waitress" not in command.lower() or "app:app" not in command:
                    raise SetupError("Service PID is not the expected Waitress app:app; left untouched")
                if not (directory / "app.py").is_file() or not (directory / "hub/core.py").is_file():
                    raise SetupError("Cannot verify the WVW project directory")
                if app_dir and Path(app_dir).resolve() != directory:
                    raise SetupError("--app-dir does not match the service process")
                listeners = self.command("ss", "-H", "-ltnp").stdout.decode()
                app_lines = [line for line in listeners.splitlines() if re.search(r":5000\s", line)]
                if not app_lines or any("127.0.0.1:5000" not in line or not re.search(rf"pid={pid}(?:,|\))", line) for line in app_lines):
                    raise SetupError("App must be verified PID bound only to 127.0.0.1:5000; no unknown process is changed")
                if user:
                    status = (proc / "status").read_text()
                    if not re.search(rf"(?m)^Uid:\s+{self.account(user).pw_uid}\s+{self.account(user).pw_uid}\b", status):
                        raise SetupError("User service PID belongs to a different account")
                self.app_user = user
                return unit, pid, str(directory)
        raise SetupError("No verified WVW systemd Waitress service; provide --app-service and bind 127.0.0.1:5000")

    def check_ports(self, proxy):
        allowed = "nginx" if proxy == "nginx" else "apache2"
        for line in self.command("ss", "-H", "-ltnp").stdout.decode().splitlines():
            if re.search(r":(?:80|443)\s", line) and f'"{allowed}"' not in line:
                raise SetupError("Port 80/443 has a different or unknown owner; left untouched")

    def check_names(self, proxy, dns, ip):
        names = [v for v in (dns, ip) if v]
        roots = [self.path("/etc/nginx/sites-enabled"), self.path("/etc/nginx/conf.d")] if proxy == "nginx" else [self.path("/etc/apache2/sites-enabled"), self.path("/etc/apache2/conf-enabled")]
        files = set()
        for folder in roots:
            if not folder.exists():
                continue
            for file in folder.iterdir():
                if file.is_file():
                    files.add(file)
        effective = ""
        if self.which("nginx" if proxy == "nginx" else "apache2ctl"):
            answer = self.command("nginx", "-T") if proxy == "nginx" else self.command("apache2ctl", "-S")
            effective = (answer.stdout + answer.stderr).decode(errors="replace")
            included = re.findall(r"(?m)^# configuration file (/.+):\s*$", effective) if proxy == "nginx" else re.findall(r"\((/[^()]+):\d+\)", effective)
            for filename in included:
                path = self.path(filename)
                if path.is_file():
                    files.add(path)
        for file in files:
            content = file.read_text(errors="replace")
            if MARKER in content:
                continue
            content = re.sub(r"(?m)#.*$", "", content)
            pattern = r"\bserver_name\s+([^;]+);" if proxy == "nginx" else r"(?im)^\s*Server(?:Name|Alias)\s+([^\r\n]+)"
            for group in re.findall(pattern, content):
                for configured in group.split():
                    configured = configured.strip("\"'")
                    conflict = any(fnmatch.fnmatchcase(name.lower(), configured.lower()) for name in names)
                    if proxy == "nginx" and configured.startswith("."):
                        conflict |= any(name == configured[1:] or name.endswith(configured) for name in names)
                    if proxy == "nginx" and configured.startswith("~"):
                        raise SetupError(f"Existing regex server_name requires manual conflict review: {file}; no site changed")
                    if conflict:
                        raise SetupError(f"Existing site already owns {configured}: {file}; not overwritten")

    def fingerprint(self):
        raw = self.ssl("x509", "-in", self.pki / "rootCA.crt", "-outform", "DER").stdout
        return hashlib.sha256(raw).hexdigest().upper()

    def key_matches(self, cert, key):
        public = self.ssl("x509", "-in", cert, "-pubkey", "-noout").stdout
        actual = self.ssl("pkey", "-in", key, "-pubout").stdout
        if public.strip() != actual.strip():
            raise SetupError("Certificate/private key mismatch")

    def ensure_ca(self, create=True):
        key, cert = self.pki / "rootCA.key", self.pki / "rootCA.crt"
        if key.exists() != cert.exists() or key.is_symlink() or cert.is_symlink():
            raise SetupError("Incomplete/unsafe existing CA; refusing automatic CA replacement")
        created = not key.exists()
        if created and not create:
            raise SetupError("CA is missing; renewal never creates a replacement root")
        if cert.exists() and b"PRIVATE KEY" in cert.read_bytes():
            raise SetupError("rootCA.crt must contain only the public root certificate; keep the key in rootCA.key")
        if created:
            staged = self.pki / ("ca-" + str(time.time_ns()))
            staged.mkdir(mode=0o700)
            try:
                self.ssl("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256", "-days", "3650", "-subj", "/CN=VWSHub Local Root CA", "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0", "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-keyout", staged / "rootCA.key", "-out", staged / "rootCA.crt")
                os.chmod(staged / "rootCA.key", 0o600)
                self.key_matches(staged / "rootCA.crt", staged / "rootCA.key")
                os.replace(staged / "rootCA.key", key)
                os.replace(staged / "rootCA.crt", cert)
            finally:
                for child in staged.iterdir():
                    child.unlink()
                staged.rmdir()
        os.chmod(key, 0o600)
        os.chmod(cert, 0o644)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            if key.stat().st_uid != 0 or cert.stat().st_uid != 0:
                raise SetupError("Existing CA files must be owned by root")
        self.key_matches(cert, key)
        self.ssl("verify", "-check_ss_sig", "-CAfile", cert, cert)
        self.ssl("x509", "-in", cert, "-checkend", "86400", "-noout")
        subject = self.ssl("x509", "-in", cert, "-noout", "-subject", "-issuer", "-nameopt", "RFC2253").stdout.decode().splitlines()
        if len(subject) != 2 or subject[0].split("=", 1)[1] != subject[1].split("=", 1)[1]:
            raise SetupError("Existing CA is not a self-issued root")
        constraints = self.ssl("x509", "-in", cert, "-noout", "-ext", "basicConstraints").stdout
        if b"CA:TRUE" not in constraints:
            raise SetupError("Existing root certificate is not a CA")
        return created

    def verify_server(self, directory, dns, ip, seconds=86400):
        cert, key = directory / "server.crt", directory / "server.key"
        if cert.is_symlink() or key.is_symlink():
            raise SetupError("Unexpected certificate/key symlink")
        self.key_matches(cert, key)
        self.ssl("verify", "-purpose", "sslserver", "-CAfile", self.pki / "rootCA.crt", cert)
        self.ssl("x509", "-in", cert, "-checkend", str(seconds), "-noout")
        purpose = self.ssl("x509", "-in", cert, "-noout", "-ext", "extendedKeyUsage").stdout
        if b"TLS Web Server Authentication" not in purpose:
            raise SetupError("Certificate must explicitly permit serverAuth")
        constraints = self.ssl("x509", "-in", cert, "-noout", "-ext", "basicConstraints").stdout
        if b"CA:FALSE" not in constraints:
            raise SetupError("Server certificate must explicitly declare CA:FALSE")
        if os.name == "posix" and (key.stat().st_mode & 0o077):
            raise SetupError("Server private key must not be readable by group/others")
        san = self.ssl("x509", "-in", cert, "-noout", "-ext", "subjectAltName").stdout.decode()
        expected = {"DNS:" + dns} if dns else set()
        if ip:
            expected.add("IP Address:" + ip)
        actual = {x.strip() for x in san.splitlines()[1:] for x in x.split(",") if x.strip()}
        if actual != expected:
            raise SetupError("Certificate SAN does not exactly match requested identities")
        if dns:
            self.ssl("verify", "-CAfile", self.pki / "rootCA.crt", "-verify_hostname", dns, cert)
        if ip:
            self.ssl("verify", "-CAfile", self.pki / "rootCA.crt", "-verify_ip", ip, cert)

    def issue(self, dns, ip):
        directory = self.pki / "versions" / str(time.time_ns())
        directory.mkdir(parents=True, mode=0o700)
        os.chmod(directory.parent, 0o700)
        san = ",".join((["DNS:" + dns] if dns else []) + (["IP:" + ip] if ip else []))
        extension = directory / "extensions.cnf"
        self.atomic(extension, ("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=" + san + "\n").encode())
        self.ssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256", "-subj", "/CN=" + (dns or ip), "-keyout", directory / "server.key", "-out", directory / "server.csr")
        os.chmod(directory / "server.key", 0o600)
        expiry = self.ssl("x509", "-in", self.pki / "rootCA.crt", "-noout", "-enddate").stdout.decode().strip().split("=", 1)[1]
        days = min(365, int((ssl.cert_time_to_seconds(expiry) - time.time()) / 86400) - 1)
        if days < 2:
            raise SetupError("CA expires too soon; arrange an explicit root trust rotation, not automatic replacement")
        self.ssl("x509", "-req", "-in", directory / "server.csr", "-CA", self.pki / "rootCA.crt", "-CAkey", self.pki / "rootCA.key", "-set_serial", "0x" + os.urandom(16).hex(), "-days", str(days), "-sha256", "-extfile", extension, "-out", directory / "server.crt")
        os.chmod(directory / "server.crt", 0o644)
        self.verify_server(directory, dns, ip)
        return directory

    def switch(self, directory, transaction):
        link = self.pki / "current"
        if link.exists() and not link.is_symlink():
            raise SetupError("Certificate current path is not an installer symlink")
        transaction.remember(link)
        temporary = self.pki / (".current-" + str(time.time_ns()))
        temporary.symlink_to(directory.relative_to(self.pki), target_is_directory=True)
        os.replace(temporary, link)

    def configuration(self, proxy, dns, ip):
        host = dns or ip
        cert, key = self.pki / "current/server.crt", self.pki / "current/server.key"
        if proxy == "nginx":
            return f'''# {MARKER}
server {{
    listen 80;
    server_name {" ".join(v for v in (dns, ip) if v)};
    return 308 https://{host}$request_uri;
}}
server {{
    listen 443 ssl;
    server_name {" ".join(v for v in (dns, ip) if v)};
    ssl_certificate {cert};
    ssl_certificate_key {key};
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 20m;
    location / {{
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Port 443;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Forwarded "";
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_connect_timeout 10s;
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
    }}
}}
'''
        alias = "\n    ServerAlias " + ip if dns and ip else ""
        return f'''# {MARKER}
<VirtualHost *:80>
    ServerName {host}{alias}
    Redirect permanent / https://{host}/
</VirtualHost>
<VirtualHost *:443>
    ServerName {host}{alias}
    SSLEngine on
    SSLCertificateFile {cert}
    SSLCertificateKeyFile {key}
    SSLProtocol -all +TLSv1.2 +TLSv1.3
    ProxyRequests Off
    ProxyPreserveHost On
    ProxyTimeout 900
    Timeout 900
    RequestHeader unset Forwarded
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Port "443"
    RequestHeader set X-Forwarded-Host "expr=%{{HTTP_HOST}}"
    RequestHeader set X-Forwarded-For "expr=%{{REMOTE_ADDR}}"
    SetEnv no-gzip 1
    ProxyPass / http://127.0.0.1:5000/ connectiontimeout=10 timeout=900 retry=0
    ProxyPassReverse / http://127.0.0.1:5000/
</VirtualHost>
'''

    def syntax(self, proxy):
        self.command("nginx", "-t") if proxy == "nginx" else self.command("apache2ctl", "configtest")

    def proxy_paths(self, proxy):
        folder = "nginx" if proxy == "nginx" else "apache2"
        return (self.path(f"/etc/{folder}/sites-available/zz-vwshub-https.conf"), self.path(f"/etc/{folder}/sites-enabled/zz-vwshub-https.conf"))

    def install_proxy(self, proxy, dns, ip, transaction):
        if proxy == "apache":
            for module in ("mime", "setenvif", "socache_shmcb", "ssl", "proxy", "proxy_http", "headers", "alias"):
                for suffix in ("load", "conf"):
                    source = self.path(f"/etc/apache2/mods-available/{module}.{suffix}")
                    target = self.path(f"/etc/apache2/mods-enabled/{module}.{suffix}")
                    if source.exists() and not (target.exists() or target.is_symlink()):
                        transaction.link(target, source)
            configs = [self.path("/etc/apache2/ports.conf"), *self.path("/etc/apache2/conf-enabled").glob("*"), *self.path("/etc/apache2/sites-enabled").glob("*")]
            if not any(p.is_file() and re.search(r"(?im)^\s*Listen\s+(?:[^\s:]+:)?443\b", p.read_text(errors="replace")) for p in configs):
                listen = self.path("/etc/apache2/conf-available/vwshub-https-listen.conf")
                transaction.write(listen, f"# {MARKER}\nListen 443\n")
                transaction.link(self.path("/etc/apache2/conf-enabled/vwshub-https-listen.conf"), listen)
        available, enabled = self.proxy_paths(proxy)
        transaction.write(available, self.configuration(proxy, dns, ip))
        transaction.link(enabled, available)

    def install_runtime(self, state, transaction):
        lib = self.path("/usr/local/lib/vwshub-https")
        transaction.write(lib / "vwshub-https.py", Path(__file__).read_bytes(), 0o755)
        transaction.write(lib / "windows/install-vwshub-ca.ps1", (Path(__file__).parent / "windows/install-vwshub-ca.ps1").read_bytes())
        wrapper = f'#!/bin/sh\n# {MARKER}\nexec /usr/bin/python3 /usr/local/lib/vwshub-https/vwshub-https.py "$@"\n'
        transaction.write(self.path("/usr/local/sbin/vwshub-https"), wrapper, 0o755)
        dropin = self.app_dropin(state)
        transaction.write(dropin, f"# {MARKER}\n[Service]\nEnvironment=COOKIE_SECURE=1\nEnvironment=VWSHUB_TRUST_PROXY=1\n")
        transaction.write(self.path("/etc/systemd/system/vwshub-https-renew.service"), f"# {MARKER}\n[Unit]\nDescription=Renew WVW local TLS certificate\n[Service]\nType=oneshot\nUMask=0077\nExecStart=/usr/local/sbin/vwshub-https renew --if-expiring\n")
        transaction.write(self.path("/etc/systemd/system/vwshub-https-renew.timer"), f"# {MARKER}\n[Unit]\nDescription=Check WVW TLS certificate daily\n[Timer]\nOnCalendar=daily\nRandomizedDelaySec=3600\nPersistent=true\n[Install]\nWantedBy=timers.target\n")

    def health(self, state):
        context = ssl.create_default_context(cafile=str(self.pki / "rootCA.crt"))
        host = state["dns"] or state["ip"]
        for route in ("/login", "/setup"):
            with socket.create_connection(("127.0.0.1", 443), timeout=5) as connection:
                with context.wrap_socket(connection, server_hostname=host) as tls:
                    tls.sendall(f"GET {route} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
                    response = b""
                    while b"\r\n\r\n" not in response and len(response) < 65536:
                        chunk = tls.recv(4096)
                        if not chunk:
                            break
                        response += chunk
            headers = response.split(b"\r\n\r\n", 1)[0]
            if not re.match(rb"HTTP/1\.[01] (200|30[12378])\b", headers):
                raise SetupError("HTTPS/app verification failed; configuration will be rolled back")
            cookies = re.findall(rb"(?im)^Set-Cookie:([^\r\n]+)", headers)
            if any(re.search(rb";\s*Secure(?:;|$)", cookie, re.I) and re.search(rb";\s*HttpOnly(?:;|$)", cookie, re.I) for cookie in cookies):
                return
        raise SetupError("Application did not set a Secure/HttpOnly session cookie over HTTPS; service environment may not have applied")

    def wait_health(self, state):
        # systemd Type=simple may return before Waitress has imported the app.
        for attempt in range(5):
            try:
                return self.health(state)
            except (SetupError, OSError, ssl.SSLError):
                if attempt == 4:
                    raise
                self.pause(1)

    def export(self, state=None):
        state = state or self.load()
        allowed = {"rootCA.crt", "install-vwshub-ca.ps1", "README.txt", "SHA256.txt", "connection.json"}
        if self.package.is_symlink():
            raise SetupError("Client package cannot be a symlink")
        self.package.mkdir(parents=True, exist_ok=True, mode=0o700)
        if any(p.name not in allowed or p.is_symlink() or not p.is_file() for p in self.package.iterdir()):
            raise SetupError("Client package contains unexpected files; no keys will be exported")
        fingerprint = self.fingerprint()
        url = "https://" + (state["dns"] or state["ip"])
        script = Path(__file__).parent / "windows/install-vwshub-ca.ps1"
        public = self.ssl("x509", "-in", self.pki / "rootCA.crt", "-outform", "PEM").stdout
        if not re.fullmatch(rb"-----BEGIN CERTIFICATE-----[\r\n]+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----[\r\n]*", public):
            raise SetupError("CA export did not produce exactly one canonical public certificate")
        self.atomic(self.package / "rootCA.crt", public, 0o644)
        self.atomic(self.package / "install-vwshub-ca.ps1", script.read_bytes(), 0o644)
        self.atomic(self.package / "SHA256.txt", (fingerprint + "\n").encode(), 0o644)
        self.atomic(self.package / "connection.json", json.dumps({"url": url, "sha256": fingerprint}).encode(), 0o644)
        text = "WVW trust package: PUBLIC certificates only.\nObtain the SHA-256 fingerprint from the server administrator through an independent trusted channel.\nRun PowerShell as administrator:\n.\\install-vwshub-ca.ps1 -CertificatePath .\\rootCA.crt -ExpectedFingerprint " + fingerprint + " -Url " + url + "\nCompare fingerprints and confirm explicitly. Do not trust a fingerprint received only over the same untrusted HTTP download.\n"
        self.atomic(self.package / "README.txt", text.encode(), 0o644)
        return fingerprint

    def install(self, dns, ip, app_service=None, app_dir=None, proxy=None, app_user=None):
        dns, ip = identities(dns, ip)
        service, _, directory = self.verify_app(app_service, app_dir, app_user)
        app_identity = self.app_identity(service)
        selected, needs_package = self.detect_proxy(proxy)
        self.check_ports(selected)
        self.check_names(selected, dns, ip)
        if needs_package:
            self.command("apt-get", "update")
            self.command("apt-get", "install", "-y", "apache2" if selected == "apache" else "nginx", "openssl", "ca-certificates")
        self.prepare()
        ca_created = self.ensure_ca()
        state = {"dns": dns, "ip": ip, "proxy": selected, "app_service": service, "app_user": self.app_user, "app_dir": directory, "installed": True, "ca_created": ca_created}
        transaction = Transaction(self)
        timer_enabled = self.enabled("vwshub-https-renew.timer")
        app_restarted = False
        try:
            current = self.pki / "current"
            try:
                self.verify_server(current.resolve(strict=True), dns, ip, 30 * 86400)
            except (SetupError, OSError):
                self.switch(self.issue(dns, ip), transaction)
            self.install_proxy(selected, dns, ip, transaction)
            self.install_runtime(state, transaction)
            self.syntax(selected)
            self.verify_app(service, directory)
            self.command("systemctl", "daemon-reload")
            if self.app_user:
                self.app_action("daemon-reload")
            app_restarted = True
            self.app_action("restart", service)
            self.command("systemctl", "reload-or-restart", "apache2" if selected == "apache" else "nginx")
            self.wait_health(state)
            self.command("systemctl", "enable", "--now", "vwshub-https-renew.timer")
            state["last_backup"] = str(transaction.directory)
            transaction.write(self.state_path, json.dumps(state), 0o600, managed=False)
            self.export(state)
        except Exception:
            transaction.rollback()
            if not timer_enabled:
                self.command("systemctl", "disable", "--now", "vwshub-https-renew.timer", check=False)
            self.command("systemctl", "daemon-reload", check=False)
            if self.app_user:
                self.app_action("daemon-reload", check=False)
            if app_restarted:
                # Restart only the same verified service, never kill an unknown PID.
                try:
                    self.restore_app(service, directory, app_identity)
                except SetupError as recovery_error:
                    print("Rollback restored files, but application recovery needs attention: " + str(recovery_error), file=sys.stderr)
            try:
                self.syntax(selected)
                self.command("systemctl", "reload-or-restart", "apache2" if selected == "apache" else "nginx", check=False)
            except SetupError:
                pass
            raise
        return state

    def renew(self, if_expiring=False):
        state = self.load()
        if not state.get("installed"):
            raise SetupError("HTTPS is uninstalled; renewal is disabled")
        self.prepare()
        self.ensure_ca(create=False)  # never creates or rotates a root during renewal
        if if_expiring:
            try:
                self.verify_server((self.pki / "current").resolve(strict=True), state["dns"], state["ip"], 30 * 86400)
                return False
            except (SetupError, OSError):
                pass
        transaction = Transaction(self)
        try:
            self.switch(self.issue(state["dns"], state["ip"]), transaction)
            self.syntax(state["proxy"])
            self.command("systemctl", "reload", "apache2" if state["proxy"] == "apache" else "nginx")
            self.wait_health(state)
        except Exception:
            transaction.rollback()
            self.syntax(state["proxy"])
            self.command("systemctl", "reload", "apache2" if state["proxy"] == "apache" else "nginx", check=False)
            raise
        return True

    def uninstall(self, restore_backup=None):
        state = self.load()
        self.app_user = state.get("app_user", "")
        self.verify_app(state["app_service"], state["app_dir"])
        app_identity = self.app_identity(state["app_service"])
        transaction = Transaction(self)
        timer_enabled = self.enabled("vwshub-https-renew.timer")
        restarted = False
        paths = [*self.proxy_paths(state["proxy"]), self.app_dropin(state), self.path("/etc/systemd/system/vwshub-https-renew.service"), self.path("/etc/systemd/system/vwshub-https-renew.timer"), self.path("/etc/apache2/conf-enabled/vwshub-https-listen.conf"), self.path("/etc/apache2/conf-available/vwshub-https-listen.conf")]
        if state["proxy"] == "apache":
            shared_listener = any(file.is_file() and MARKER not in file.read_text(errors="replace") and re.search(r"(?i)<VirtualHost\s+[^>]*:443\b", file.read_text(errors="replace")) for file in self.path("/etc/apache2/sites-enabled").glob("*"))
            if shared_listener:
                paths = [path for path in paths if path.name != "vwshub-https-listen.conf"]
        try:
            for path in paths:
                if path.exists() or path.is_symlink():
                    if MARKER not in path.read_text():
                        raise SetupError("Managed file was replaced by foreign content; left untouched: " + str(path))
                    transaction.remove(path)
            if restore_backup:
                folder = Path(restore_backup).resolve(strict=True)
                if folder.parent != (self.base / "backups").resolve() or folder.is_symlink():
                    raise SetupError("Backup must be an installer backup directory")
                records = json.loads((folder / "journal.json").read_text())
                previous_state = next((record for record in records if record["path"] == str(self.state_path)), None)
                restored_state = json.loads(base64.b64decode(previous_state["data"])) if previous_state and "data" in previous_state else None
                if restored_state:
                    identities(restored_state["dns"], restored_state["ip"])
                    if any(restored_state.get(key, "") != state.get(key, "") for key in ("app_service", "app_user", "app_dir", "proxy")):
                        raise SetupError("Backup belongs to a different application deployment; restore it manually after review")
                allowed = {str(p) for p in paths} | {str(self.pki / "current")}
                for record in records:
                    if record["path"] not in allowed:
                        continue
                    path = Path(record["path"])
                    if path == self.pki / "current":
                        if not restored_state or "link" not in record:
                            continue  # uninstall retains CA/leaf material from a first install
                        target = Path(record["link"])
                        if target.is_absolute() or len(target.parts) != 2 or target.parts[0] != "versions":
                            raise SetupError("Invalid certificate pointer in installer backup")
                    transaction.remember(path)
                    if path.exists() or path.is_symlink():
                        path.unlink()
                    if "link" in record:
                        path.symlink_to(record["link"])
                    elif "data" in record:
                        self.atomic(path, base64.b64decode(record["data"]), record["mode"])
                if restored_state:
                    state = restored_state
                    self.verify_server((self.pki / "current").resolve(strict=True), state["dns"], state["ip"], 0)
            self.syntax(state["proxy"])
            self.verify_app(state["app_service"], state["app_dir"])
            self.command("systemctl", "disable", "--now", "vwshub-https-renew.timer")
            self.command("systemctl", "daemon-reload")
            if self.app_user:
                self.app_action("daemon-reload")
            restarted = True
            self.app_action("restart", state["app_service"])
            proxy_unit = "apache2" if state["proxy"] == "apache" else "nginx"
            if self.active(proxy_unit):
                self.command("systemctl", "reload", proxy_unit)
            state["installed"] = bool(restore_backup and self.proxy_paths(state["proxy"])[0].exists())
            if state["installed"]:
                self.wait_health(state)
                self.command("systemctl", "enable", "--now", "vwshub-https-renew.timer")
            transaction.write(self.state_path, json.dumps(state), 0o600, managed=False)
        except Exception:
            transaction.rollback()
            self.command("systemctl", "daemon-reload", check=False)
            if self.app_user:
                self.app_action("daemon-reload", check=False)
            if timer_enabled:
                self.command("systemctl", "enable", "--now", "vwshub-https-renew.timer", check=False)
            if restarted:
                try:
                    self.restore_app(state["app_service"], state["app_dir"], app_identity)
                    self.syntax(state["proxy"])
                    self.command("systemctl", "reload", "apache2" if state["proxy"] == "apache" else "nginx", check=False)
                except SetupError as recovery_error:
                    print("Rollback restored files, but application recovery needs attention: " + str(recovery_error), file=sys.stderr)
            raise
        return state

    def status(self):
        state = self.load()
        state.update(url="https://" + (state["dns"] or state["ip"]), certificate=str(self.pki / "current/server.crt"), proxy_active=self.active("apache2" if state["proxy"] == "apache" else "nginx"), renewal_enabled=self.enabled("vwshub-https-renew.timer"), client_package=str(self.package))
        try:
            self.key_matches(self.pki / "rootCA.crt", self.pki / "rootCA.key")
            self.ssl("verify", "-check_ss_sig", "-CAfile", self.pki / "rootCA.crt", self.pki / "rootCA.crt")
            self.ssl("x509", "-in", self.pki / "rootCA.crt", "-checkend", "0", "-noout")
            state.update(ca="VALID", ca_sha256=self.fingerprint())
        except (SetupError, OSError) as error:
            state.update(ca="INVALID", ca_error=str(error))
        try:
            self.verify_server((self.pki / "current").resolve(strict=True), state["dns"], state["ip"], 0)
            state.update(certificate_state="VALID", expiry=self.ssl("x509", "-in", self.pki / "current/server.crt", "-noout", "-enddate").stdout.decode().strip())
        except (SetupError, OSError) as error:
            state.update(certificate_state="INVALID", certificate_error=str(error))
        try:
            self.health(state)
            state["application"] = "VERIFIED_OVER_TLS"
        except (SetupError, OSError, ssl.SSLError) as error:
            state.update(application="UNVERIFIED", application_error=str(error))
        return state


def dns_confirmation(dns, ip, allow=False):
    if not dns:
        return
    try:
        answers = {entry[4][0] for entry in socket.getaddrinfo(dns, None, socket.AF_INET)}
    except socket.gaierror:
        answers = set()
    if answers and (not ip or ip in answers):
        return
    print("WARNING: DNS does not resolve to the requested IPv4. Configure DNS/client hosts before browser access.")
    if not allow and (not sys.stdin.isatty() or input("Continue with this SAN anyway? Type YES: ") != "YES"):
        raise SetupError("DNS confirmation required; use --allow-dns-mismatch only after reviewing the warning")


def main(argv=None):
    parser = argparse.ArgumentParser(description="VWSHub HTTPS Installer (Debian/Ubuntu)")
    parser.add_argument("command", choices=["install", "status", "renew", "export-ca", "uninstall"])
    parser.add_argument("--dns-name")
    parser.add_argument("--ip-address")
    parser.add_argument("--proxy", choices=["apache", "nginx"])
    parser.add_argument("--app-service")
    parser.add_argument("--app-dir")
    parser.add_argument("--app-user", help="Owner of an existing systemd --user Waitress service")
    parser.add_argument("--allow-dns-mismatch", action="store_true")
    parser.add_argument("--if-expiring", action="store_true")
    parser.add_argument("--restore-backup")
    options = parser.parse_args(argv)
    if sys.platform != "linux" or os.geteuid() != 0:
        parser.error("Run on the Debian/Ubuntu server as root; this installer never configures a Windows host")
    if not Path("/etc/debian_version").is_file():
        parser.error("This installer supports Debian/Ubuntu only")
    installer = Installer()
    if options.command == "status":
        # Read-only: no mkdir/chmod, lock file, daemon reload or timer changes.
        status = installer.status()
        print(json.dumps(status, indent=2))
        return 0 if status.get("installed") and status.get("ca") == "VALID" and status.get("certificate_state") == "VALID" and status.get("application") == "VERIFIED_OVER_TLS" else 1
    installer.prepare()
    import fcntl
    lock_path = installer.base / ".lock"
    if lock_path.is_symlink():
        raise SetupError("Installer lock must not be a symlink")
    with lock_path.open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if options.command == "install":
            dns, ip = options.dns_name, options.ip_address
            if dns is None and ip is None:
                print("VWSHub HTTPS Installer\nUse '-' to omit DNS or IPv4.")
                dns = input("DNS name [srv-vms.bk-base.local]: ") or "srv-vms.bk-base.local"
                ip = input("IPv4 [172.17.6.155]: ") or "172.17.6.155"
            dns, ip = identities("" if dns in (None, "-") else dns, "" if ip in (None, "-") else ip)
            dns_confirmation(dns, ip, options.allow_dns_mismatch)
            installer.install(dns, ip, options.app_service, options.app_dir, options.proxy, options.app_user)
        elif options.command == "renew":
            print("Renewed" if installer.renew(options.if_expiring) else "Certificate is not due for renewal")
        elif options.command == "export-ca":
            print("Root CA SHA256:", installer.export())
        elif options.command == "uninstall":
            installer.uninstall(options.restore_backup)
            print("Managed HTTPS configuration removed/restored. CA/keys retained. Client trust is not removed.")
            return
        status = installer.status()
        if options.command == "install":
            healthy = status.get("ca") == "VALID" and status.get("certificate_state") == "VALID" and status.get("application") == "VERIFIED_OVER_TLS" and status.get("proxy_active") and status.get("renewal_enabled")
            print("VWSHub HTTPS Setup — SUCCESS" if healthy else "VWSHub HTTPS Setup — COMPLETED WITH VERIFICATION WARNINGS")
        print(json.dumps(status, indent=2))
        if options.command == "install" and not healthy:
            return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SetupError, OSError, ValueError) as error:
        print("VWSHub HTTPS Setup — FAILED:", str(error), file=sys.stderr)
        sys.exit(1)
