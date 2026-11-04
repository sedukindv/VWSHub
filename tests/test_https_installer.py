"""Offline installer tests. No host service, trust store, apt or port is changed."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from types import SimpleNamespace

import pytest

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wvw_https_installer", PROJECT / "scripts/https/vwshub-https.py")
https = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(https)
OPENSSL = shutil.which("openssl") or ("C:/Program Files/Git/usr/bin/openssl.exe" if Path("C:/Program Files/Git/usr/bin/openssl.exe").is_file() else None)


@pytest.fixture
def work(monkeypatch):
    # Windows sandbox tokens cannot use Python's special mkdir(0700) ACL or create
    # symbolic links. The product CLI is Linux-only; POSIX permissions/link tests
    # are separately marked. Ordinary files + OpenSSL remain real in these tests.
    if os.name == "nt":
        original = Path.mkdir
        def mkdir(path, mode=0o777, parents=False, exist_ok=False):
            return original(path, mode=0o777, parents=parents, exist_ok=exist_ok)
        monkeypatch.setattr(Path, "mkdir", mkdir)
    base = PROJECT.parent / ".https-installer-tests"
    base.mkdir(exist_ok=True)
    folder = base / uuid.uuid4().hex
    folder.mkdir()
    yield folder
    assert folder.resolve().parent == base.resolve()
    shutil.rmtree(folder)


class Commands:
    def __init__(self):
        self.calls = []
        self.running = {"nginx"}
        self.timer = False
        self.syntax_fail = False
        self.listeners = 'LISTEN 0 128 127.0.0.1:5000 0.0.0.0:* users:(("waitress",pid=123,fd=6))\n'

    def __call__(self, args, check=True, input=None):
        args = [str(v) for v in args]
        self.calls.append(args)
        code, out = 0, b""
        if args[:2] == ["systemctl", "is-active"]:
            code = 0 if args[-1] in self.running else 3
        elif args[:2] == ["systemctl", "is-enabled"]:
            code = 0 if self.timer else 1
        elif args[:2] == ["systemctl", "show"]:
            out = b"123\n"
        elif args[:2] == ["systemctl", "cat"]:
            out = b"# /etc/systemd/system/vwshub.service\n[Service]\nExecStart=/venv/bin/waitress-serve --listen=127.0.0.1:5000 app:app\n"
        elif args[0] == "ss":
            out = self.listeners.encode()
        elif args == ["nginx", "-t"] or args == ["apache2ctl", "configtest"]:
            if self.syntax_fail:
                code = 1
        elif args[:2] == ["systemctl", "enable"]:
            self.timer = True
        elif args[:2] == ["systemctl", "disable"]:
            self.timer = False
        if check and code:
            raise https.SetupError("mocked syntax/command failure")
        return subprocess.CompletedProcess(args, code, out, b"mock error" if code else b"")


def fixture_installer(work):
    commands = Commands()
    install = https.Installer(root=work, run=commands, which=lambda name: "/usr/sbin/nginx" if name == "nginx" else None, pause=lambda seconds:None)
    install.prepare()
    project = install.path("/proc/123/cwd")
    (project / "hub").mkdir(parents=True)
    (project / "app.py").write_text("# isolated fixture")
    (project / "hub/core.py").write_text("# isolated fixture")
    (install.path("/proc/123/cmdline")).write_bytes(b"/venv/bin/waitress-serve\0--listen=127.0.0.1:5000\0app:app\0")
    return install, commands


@pytest.mark.parametrize("dns,ip", [("a;rm -rf /", ""), ("*.example.local", ""), ("a\nServerName evil", ""), ("a..local", ""), ("-a.local", ""), ("172.17.6.155", ""), ("", "999.1.1.1"), ("", "0.0.0.0"), ("", "224.1.2.3"), ("", "::1"), ("", "")])
def test_invalid_identities_do_not_reach_commands(dns, ip):
    with pytest.raises(https.SetupError):
        https.identities(dns, ip)


def test_service_name_cannot_be_interpreted_as_a_systemctl_option(work):
    install,commands=fixture_installer(work)
    with pytest.raises(https.SetupError,match="Invalid systemd service"):
        install.verify_app("-Hremote.service")
    assert not commands.calls


@pytest.mark.parametrize("dns,ip", [("SRV-VMS.bk-base.local.", "172.17.6.155"), ("srv.local", ""), ("", "172.17.6.155")])
def test_dns_ip_and_both_are_supported(dns, ip):
    actual = https.identities(dns, ip)
    assert actual == (dns.lower().rstrip("."), ip)


def test_dns_mismatch_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(https.socket, "getaddrinfo", lambda *a: [(None, None, None, None, ("172.17.6.10", 0))])
    monkeypatch.setattr(https.sys.stdin, "isatty", lambda: False)
    with pytest.raises(https.SetupError, match="DNS confirmation"):
        https.dns_confirmation("srv.local", "172.17.6.155")
    https.dns_confirmation("srv.local", "172.17.6.155", allow=True)


def test_existing_proxy_is_reused_and_second_server_is_rejected(work):
    install, commands = fixture_installer(work)
    assert install.detect_proxy() == ("nginx", False)
    with pytest.raises(https.SetupError, match="second server"):
        install.detect_proxy("apache")
    commands.running.add("apache2")
    with pytest.raises(https.SetupError, match="Both"):
        install.detect_proxy()
    assert not any(call[0] == "apt-get" for call in commands.calls)


def test_default_apache_only_when_no_proxy_is_installed(work):
    install, commands = fixture_installer(work)
    commands.running.clear()
    install.which = lambda name: None
    assert install.detect_proxy() == ("apache", True)


def test_unknown_port_owner_and_foreign_named_site_are_untouched(work):
    install, commands = fixture_installer(work)
    commands.listeners += 'LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("other",pid=999,fd=1))\n'
    with pytest.raises(https.SetupError, match="unknown owner"):
        install.check_ports("nginx")
    target = install.path("/etc/nginx/sites-enabled/company.conf")
    target.parent.mkdir(parents=True)
    content = "server { server_name *.bk-base.local; listen 443 ssl; }"
    target.write_text(content)
    with pytest.raises(https.SetupError, match="already owns"):
        install.check_names("nginx", "srv-vms.bk-base.local", "172.17.6.155")
    assert target.read_text() == content


def test_app_identity_loopback_and_pid_are_verified_before_restart(work):
    install, commands = fixture_installer(work)
    assert install.verify_app("vwshub.service")[1] == 123
    commands.listeners = commands.listeners.replace("127.0.0.1", "0.0.0.0")
    with pytest.raises(https.SetupError, match="bound only"):
        install.verify_app("vwshub.service")
    commands.listeners = commands.listeners.replace("0.0.0.0:5000", "127.0.0.1:5000").replace("pid=123", "pid=999")
    with pytest.raises(https.SetupError):
        install.verify_app("vwshub.service")
    install.path("/proc/123/cmdline").write_bytes(b"unrelated-service\0app:app\0")
    with pytest.raises(https.SetupError, match="not the expected"):
        install.verify_app("vwshub.service")
    assert not any(call[:2] == ["systemctl", "restart"] for call in commands.calls)


def test_existing_user_service_uses_its_owner_bus_and_dropin(work, monkeypatch):
    install, commands = fixture_installer(work)
    bus = install.path("/run/user/1000/bus")
    bus.parent.mkdir(parents=True)
    bus.write_text("mock user bus, not a socket")
    install.path("/proc/123/status").write_text("Uid:\t1000\t1000\t1000\t1000\n")
    monkeypatch.setattr(install, "account", lambda user: SimpleNamespace(pw_uid=1000,pw_dir="/home/operator"))
    prefixes = []
    def run(args, check=True, input=None):
        if args[0] == "runuser":
            prefixes.append(args[:])
            offset = args.index("systemctl")
            return commands(["systemctl", *args[offset+2:]], check=check, input=input)
        return commands(args,check=check,input=input)
    install.run = run
    assert install.verify_app("vwshub.service", app_user="operator")[1] == 123
    assert install.app_user == "operator"
    install.app_action("daemon-reload")
    assert all("XDG_RUNTIME_DIR=/run/user/1000" in prefix and "--user" in prefix for prefix in prefixes)
    assert install.app_dropin({"app_user":"operator","app_service":"vwshub.service"}).as_posix().endswith("home/operator/.config/systemd/user/vwshub.service.d/vwshub-https.conf")
    install.path("/proc/123/status").write_text("Uid:\t999\t999\t999\t999\n")
    with pytest.raises(https.SetupError, match="different account"):
        install.verify_app("vwshub.service", app_user="operator")


@pytest.mark.parametrize("proxy", ["apache", "nginx"])
def test_proxy_configuration_has_streaming_tls_and_sanitized_forwarded_headers(work, proxy):
    install, _ = fixture_installer(work)
    text = install.configuration(proxy, "srv-vms.bk-base.local", "172.17.6.155")
    assert "127.0.0.1:5000" in text
    assert "443" in text and "80" in text and "900" in text
    assert "server.key" in text and "server.crt" in text
    assert "X-Forwarded-Proto" in text and "X-Forwarded-Host" in text
    assert "CSRF" not in text and "HEVC" not in text
    if proxy == "nginx":
        assert "proxy_buffering off" in text and "https://srv-vms.bk-base.local$request_uri" in text
    else:
        assert "ProxyPassReverse" in text and "ProxyRequests Off" in text


def test_transaction_backups_and_rollback_preserve_foreign_files(work):
    install, _ = fixture_installer(work)
    target = work / "managed.conf"
    original = "# " + https.MARKER + "\noriginal"
    target.write_text(original)
    foreign = work / "company.conf"
    foreign.write_text("company site")
    transaction = https.Transaction(install)
    transaction.write(target, "# " + https.MARKER + "\nchanged")
    created = work / "created.conf"
    transaction.write(created, "# " + https.MARKER)
    with pytest.raises(https.SetupError, match="Foreign"):
        transaction.write(foreign, "replacement")
    transaction.rollback()
    assert target.read_text() == original and not created.exists()
    assert foreign.read_text() == "company site"
    assert (transaction.directory / "journal.json").is_file()


@pytest.fixture
def certificates(work):
    if not OPENSSL:
        pytest.skip("OpenSSL unavailable; real certificate validation not run")
    probe = subprocess.run([OPENSSL, "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if probe.returncode:
        pytest.skip("OpenSSL executable unavailable in this sandbox; real CLI certificate roundtrip requires Linux CI")
    install = https.Installer(root=work, openssl=OPENSSL)
    install.prepare()
    assert install.ensure_ca() is True
    return install


def test_ca_is_reused_and_root_private_key_never_enters_client_package(certificates):
    install = certificates
    fingerprint = install.fingerprint()
    key = (install.pki / "rootCA.key").read_bytes()
    assert install.ensure_ca() is False
    assert install.fingerprint() == fingerprint and (install.pki / "rootCA.key").read_bytes() == key
    state = {"dns": "srv.local", "ip": "172.17.6.155"}
    assert install.export(state) == fingerprint
    assert {p.name for p in install.package.iterdir()} == {"rootCA.crt", "install-vwshub-ca.ps1", "README.txt", "SHA256.txt", "connection.json"}
    assert all(b"PRIVATE KEY" not in p.read_bytes() for p in install.package.iterdir() if p.suffix != ".ps1")
    metadata = json.loads((install.package / "connection.json").read_text())
    assert metadata["sha256"] == fingerprint and metadata["url"] == "https://srv.local"


@pytest.mark.parametrize("dns,ip", [("srv.local", "172.17.6.155"), ("srv.local", ""), ("", "172.17.6.155")])
def test_real_openssl_san_serverauth_chain_key_and_identity(certificates, dns, ip):
    install = certificates
    directory = install.issue(dns, ip)
    install.verify_server(directory, dns, ip)
    with pytest.raises(https.SetupError):
        install.verify_server(directory, "wrong.local", ip)
    if os.name == "posix":
        assert (install.pki / "rootCA.key").stat().st_mode & 0o777 == 0o600
        assert (directory / "server.key").stat().st_mode & 0o777 == 0o600


def test_broken_existing_ca_is_not_silently_replaced(certificates):
    install = certificates
    cert = (install.pki / "rootCA.crt").read_bytes()
    (install.pki / "rootCA.key").write_text("broken private key")
    with pytest.raises(https.SetupError):
        install.ensure_ca()
    assert (install.pki / "rootCA.crt").read_bytes() == cert
    assert (install.pki / "rootCA.key").read_text() == "broken private key"


def test_renewal_refuses_to_create_a_missing_root(work):
    install, _ = fixture_installer(work)
    with pytest.raises(https.SetupError, match="never creates"):
        install.ensure_ca(create=False)
    assert not (install.pki / "rootCA.key").exists()


def test_syntax_failure_rolls_back_before_any_app_restart(work, monkeypatch):
    install, commands = fixture_installer(work)
    commands.syntax_fail = True
    (install.pki / "current").mkdir()
    monkeypatch.setattr(install, "ensure_ca", lambda: False)
    monkeypatch.setattr(install, "verify_server", lambda *args: None)
    def proxy(proxy, dns, ip, transaction):
        transaction.write(install.path("/etc/nginx/conf.d/vwshub.conf"), "# " + https.MARKER)
    monkeypatch.setattr(install, "install_proxy", proxy)
    monkeypatch.setattr(install, "install_runtime", lambda state, transaction: None)
    with pytest.raises(https.SetupError):
        install.install("srv.local", "172.17.6.155", "vwshub.service")
    assert not install.path("/etc/nginx/conf.d/vwshub.conf").exists()
    assert not any(call[:2] == ["systemctl", "restart"] for call in commands.calls)


def test_repeated_install_and_failed_health_restore_previous_files(work, monkeypatch):
    install, commands = fixture_installer(work)
    monkeypatch.setattr(install, "ensure_ca", lambda: False)
    monkeypatch.setattr(install, "verify_server", lambda *args: None)
    monkeypatch.setattr(install, "export", lambda state: "PUBLIC-FINGERPRINT")
    current = install.pki / "current"
    current.mkdir()
    target = install.path("/etc/nginx/conf.d/vwshub.conf")
    def proxy(proxy, dns, ip, transaction):
        transaction.write(target, "# " + https.MARKER + "\nserver_name " + dns)
    monkeypatch.setattr(install, "install_proxy", proxy)
    monkeypatch.setattr(install, "install_runtime", lambda state, transaction: None)
    monkeypatch.setattr(install, "health", lambda state: None)
    install.install("srv.local", "172.17.6.155", "vwshub.service")
    before = target.read_bytes()
    install.install("srv.local", "172.17.6.155", "vwshub.service")
    assert target.read_bytes() == before
    assert len(list(target.parent.glob("*.conf"))) == 1
    monkeypatch.setattr(install, "health", lambda state: (_ for _ in ()).throw(https.SetupError("health failed")))
    with pytest.raises(https.SetupError, match="health"):
        install.install("changed.local", "172.17.6.155", "vwshub.service")
    assert target.read_bytes() == before
    assert install.load()["dns"] == "srv.local"


def test_renewal_error_restores_old_leaf_and_never_replaces_ca(work, monkeypatch):
    install, commands = fixture_installer(work)
    state = {"dns": "srv.local", "ip": "172.17.6.155", "proxy": "nginx", "app_service": "vwshub.service", "installed": True}
    install.atomic(install.state_path, json.dumps(state).encode())
    old_ca = install.pki / "rootCA.crt"
    old_ca.write_bytes(b"existing CA unchanged")
    pointer = install.pki / "test-current-pointer"
    pointer.write_text("old valid leaf")
    observed = []
    monkeypatch.setattr(install, "ensure_ca", lambda create: observed.append(create))
    monkeypatch.setattr(install, "issue", lambda dns, ip: Path("new-validated-leaf"))
    monkeypatch.setattr(install, "switch", lambda directory, transaction: transaction.write(pointer, str(directory), managed=False))
    monkeypatch.setattr(install, "health", lambda state: (_ for _ in ()).throw(https.SetupError("renew TLS failed")))
    with pytest.raises(https.SetupError, match="renew TLS"):
        install.renew()
    assert observed == [False]
    assert pointer.read_text() == "old valid leaf"
    assert old_ca.read_bytes() == b"existing CA unchanged"
    assert not any(call[:2] == ["systemctl", "restart"] for call in commands.calls)


def test_renewal_timer_does_nothing_before_expiry(work, monkeypatch):
    install, commands = fixture_installer(work)
    state = {"dns": "srv.local", "ip": "", "proxy": "nginx", "app_service": "vwshub.service", "installed": True}
    install.atomic(install.state_path, json.dumps(state).encode())
    (install.pki / "current").mkdir()
    monkeypatch.setattr(install, "ensure_ca", lambda create: None)
    monkeypatch.setattr(install, "verify_server", lambda *args: None)
    monkeypatch.setattr(install, "issue", lambda *args: pytest.fail("unnecessary certificate replacement"))
    assert install.renew(if_expiring=True) is False
    assert not any(call[:2] in (["systemctl", "restart"], ["systemctl", "reload"]) for call in commands.calls)


def test_uninstall_removes_only_installer_configuration_and_keeps_ca(work):
    install, commands = fixture_installer(work)
    state = {"dns": "srv.local", "ip": "", "proxy": "nginx", "app_service": "vwshub.service", "app_dir": str(install.path("/proc/123/cwd")), "installed": True}
    install.atomic(install.state_path, json.dumps(state).encode())
    available = install.proxy_paths("nginx")[0]
    install.atomic(available, ("# " + https.MARKER).encode(), 0o644)
    foreign = available.parent / "company.conf"
    foreign.write_text("unrelated site")
    key = install.pki / "rootCA.key"
    key.write_text("isolated test key, not a real secret")
    commands.timer = True
    result = install.uninstall()
    assert not result["installed"] and not available.exists()
    assert foreign.read_text() == "unrelated site"
    assert key.is_file() and commands.timer is False


def test_public_package_and_der_fingerprint_without_external_openssl(work, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    install, _ = fixture_installer(work)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Isolated test CA")])
    now = datetime.now(timezone.utc)
    certificate = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=10)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).sign(key,hashes.SHA256())
    pem = certificate.public_bytes(serialization.Encoding.PEM)
    der = certificate.public_bytes(serialization.Encoding.DER)
    private = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    # Regression: a legacy combined PEM must never leak its trailing key.
    (install.pki / "rootCA.crt").write_bytes(pem+private)
    (install.pki / "rootCA.key").write_bytes(private)
    def certificate_cli(*args):
        return subprocess.CompletedProcess(args,0,pem if args[-1]=="PEM" else der,b"")
    monkeypatch.setattr(install, "ssl", certificate_cli)
    expected = certificate.fingerprint(hashes.SHA256()).hex().upper()
    assert install.fingerprint() == expected
    assert install.export({"dns":"srv.local","ip":""}) == expected
    assert (install.package / "rootCA.crt").read_bytes() == pem
    assert not list(install.package.glob("*.key"))
    assert all(b"BEGIN PRIVATE KEY" not in path.read_bytes() for path in install.package.iterdir())


def test_restart_failure_pid_zero_restores_the_exact_known_unit(work, monkeypatch):
    install, commands = fixture_installer(work)
    (install.pki / "current").mkdir()
    monkeypatch.setattr(install,"ensure_ca",lambda:False)
    monkeypatch.setattr(install,"verify_server",lambda *args:None)
    monkeypatch.setattr(install,"install_proxy",lambda *args:None)
    dropin=install.app_dropin({"app_service":"vwshub.service"})
    monkeypatch.setattr(install,"install_runtime",lambda state,transaction:transaction.write(dropin,"# "+https.MARKER+"\nEnvironment=COOKIE_SECURE=1"))
    failed=[False]
    restarted=[]
    def runner(args,check=True,input=None):
        if args[:2]==["systemctl","restart"]:
            restarted.append(args[-1])
            if not failed[0]:
                failed[0]=True
                commands.listeners=""
                raise https.SetupError("new service environment failed")
            return subprocess.CompletedProcess(args,0,b"",b"")
        if args[:2]==["systemctl","show"] and failed[0]:
            return subprocess.CompletedProcess(args,0,b"0\n",b"")
        return commands(args,check=check,input=input)
    install.run=runner
    with pytest.raises(https.SetupError,match="new service environment"):
        install.install("srv.local","172.17.6.155","vwshub.service")
    assert restarted==["vwshub.service","vwshub.service"]
    assert not dropin.exists()


def test_expired_ca_renewal_fails_closed_without_rotating_root(work,monkeypatch):
    install,_=fixture_installer(work)
    state={"dns":"srv.local","ip":"","proxy":"nginx","app_service":"vwshub.service","installed":True}
    install.atomic(install.state_path,json.dumps(state).encode())
    (install.pki/"rootCA.crt").write_bytes(b"isolated old public certificate")
    (install.pki/"rootCA.key").write_bytes(b"isolated old key")
    monkeypatch.setattr(install,"key_matches",lambda *args:None)
    monkeypatch.setattr(install,"ssl",lambda *args,**kwargs:(_ for _ in ()).throw(https.SetupError("certificate has expired")))
    monkeypatch.setattr(install,"issue",lambda *args:pytest.fail("must not sign with an expired CA"))
    with pytest.raises(https.SetupError,match="expired"):
        install.renew()
    assert (install.pki/"rootCA.crt").read_bytes()==b"isolated old public certificate"
    assert (install.pki/"rootCA.key").read_bytes()==b"isolated old key"


def test_uninstall_restart_failure_pid_zero_restores_known_service_and_files(work):
    install,commands=fixture_installer(work)
    state={"dns":"srv.local","ip":"","proxy":"nginx","app_service":"vwshub.service","app_dir":str(install.path("/proc/123/cwd")),"installed":True}
    install.atomic(install.state_path,json.dumps(state).encode())
    site=install.proxy_paths("nginx")[0]
    dropin=install.app_dropin(state)
    original=("# "+https.MARKER+"\nold configuration").encode()
    install.atomic(site,original,0o644);install.atomic(dropin,original,0o644)
    failed=[False];restarted=[]
    def runner(args,check=True,input=None):
        if args[:2]==["systemctl","restart"]:
            restarted.append(args[-1])
            if not failed[0]:
                failed[0]=True;commands.listeners=""
                raise https.SetupError("restart failed")
            return subprocess.CompletedProcess(args,0,b"",b"")
        if args[:2]==["systemctl","show"] and failed[0]:
            return subprocess.CompletedProcess(args,0,b"0\n",b"")
        return commands(args,check=check,input=input)
    install.run=runner
    with pytest.raises(https.SetupError,match="restart failed"):
        install.uninstall()
    assert restarted==["vwshub.service","vwshub.service"]
    assert site.read_bytes()==original and dropin.read_bytes()==original
    assert install.load()["installed"] is True


@pytest.mark.parametrize("header,valid",[(b"HTTP/1.1 200 OK\r\nSet-Cookie: session=demo; HttpOnly; Secure; SameSite=Lax\r\n\r\n",True),(b"HTTP/1.1 200 OK\r\nSet-Cookie: session=demo; HttpOnly\r\n\r\n",False),(b"HTTP/1.1 502 Bad Gateway\r\n\r\n",False)])
def test_tls_probe_requires_real_secure_httponly_response_header(work,monkeypatch,header,valid):
    install,_=fixture_installer(work)
    sent=[]
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    class TLS(Connection):
        delivered=False
        def sendall(self,value):sent.append(value)
        def recv(self,size):
            if self.delivered:return b""
            self.delivered=True;return header
    class Context:
        def wrap_socket(self,connection,server_hostname):
            assert server_hostname=="srv.local"
            return TLS()
    monkeypatch.setattr(https.ssl,"create_default_context",lambda cafile:Context())
    monkeypatch.setattr(https.socket,"create_connection",lambda address,timeout:Connection())
    if valid:install.health({"dns":"srv.local","ip":""})
    else:
        with pytest.raises(https.SetupError):install.health({"dns":"srv.local","ip":""})
    assert sent and b"Host: srv.local" in sent[0]


def test_status_cli_does_not_prepare_mutate_or_lock(monkeypatch):
    class ReadOnlyInstaller:
        def prepare(self):pytest.fail("status must not prepare filesystem")
        def status(self):return {"installed":True,"ca":"VALID","certificate_state":"VALID","application":"VERIFIED_OVER_TLS"}
    original=Path.is_file
    monkeypatch.setattr(Path,"is_file",lambda path:True if path.as_posix().endswith("/etc/debian_version") else original(path))
    monkeypatch.setattr(https.sys,"platform","linux")
    monkeypatch.setattr(https.os,"geteuid",lambda:0,raising=False)
    monkeypatch.setattr(https,"Installer",ReadOnlyInstaller)
    assert https.main(["status"])==0


@pytest.mark.skipif(os.name != "posix", reason="POSIX atomic symlink switch/permissions require a Linux filesystem")
def test_atomic_certificate_switch_rollback_keeps_old_ca_and_leaf(certificates):
    install = certificates
    first = install.issue("srv.local", "172.17.6.155")
    install.switch(first, https.Transaction(install))
    fingerprint = install.fingerprint()
    transaction = https.Transaction(install)
    second = install.issue("srv.local", "172.17.6.155")
    install.switch(second, transaction)
    assert (install.pki / "current").resolve() == second
    transaction.rollback()
    assert (install.pki / "current").resolve() == first
    assert install.fingerprint() == fingerprint


def test_windows_import_script_has_explicit_admin_fingerprint_ca_and_no_removal():
    text = (PROJECT / "scripts/https/windows/install-vwshub-ca.ps1").read_text()
    for term in ["Administrator", "ExpectedFingerprint", "SHA256", "CertificateAuthority", "KeyCertSign", "StoreLocation]::LocalMachine", "TRUST", "HasPrivateKey"]:
        assert term in text
    assert "Remove-Item" not in text and "-Confirm:$false" not in text
    confirmation = text.index("Type TRUST")
    importing = text.index("$store.Add($certificate)")
    assert confirmation < importing
    assert "Import-Certificate" not in text[confirmation:]
    assert "ReadAllText" not in text[confirmation:]
