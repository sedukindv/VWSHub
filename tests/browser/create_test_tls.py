"""Disposable loopback TLS identity for CI. Does not modify any trust store."""
import ipaddress
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

target=Path(sys.argv[1]).resolve()
target.mkdir(parents=True,exist_ok=True)
now=datetime.now(timezone.utc)
ca_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'WVW disposable loopback QA CA')])
ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
    .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=2))
    .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
    .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,None,None),critical=True)
    .sign(ca_key,hashes.SHA256()))
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
leaf=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')]))
      .issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
      .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=1))
      .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
      .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
      .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
      .add_extension(x509.KeyUsage(True,False,True,False,False,False,False,None,None),critical=True)
      .sign(ca_key,hashes.SHA256()))
for filename,raw in {'ca.crt':ca.public_bytes(serialization.Encoding.PEM),'server.crt':leaf.public_bytes(serialization.Encoding.PEM),'server.key':key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())}.items():
 path=target/filename
 if path.exists():raise SystemExit('Refusing to replace an existing QA TLS file: '+filename)
 path.write_bytes(raw)
 if os.name!='nt':path.chmod(0o600 if filename.endswith('.key') else 0o644)
print('Created disposable loopback QA identity; no trust stores changed.')
