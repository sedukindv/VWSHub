"""One explicit, loopback-only reverse proxy boundary for HTTPS deployments."""
import ipaddress
from werkzeug.middleware.proxy_fix import ProxyFix


class LoopbackProxy:
    def __init__(self, app):
        self.app = app
        # Do not accept a forwarded client address or path prefix. The local
        # Apache/Nginx installer overwrites these three origin headers.
        self.forwarded = ProxyFix(app, x_for=0, x_proto=1, x_host=1, x_port=1, x_prefix=0)

    def __call__(self, environ, start_response):
        try:
            trusted = ipaddress.ip_address(environ.get("REMOTE_ADDR", "")).is_loopback
        except ValueError:
            trusted = False
        return (self.forwarded if trusted else self.app)(environ, start_response)
