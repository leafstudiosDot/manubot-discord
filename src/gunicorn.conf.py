"""Gunicorn configuration for Manubot.

The Discord Gateway must only be connected once per host. Do not increase
``workers``: keep a single worker and raise ``WEB_THREADS`` instead.
"""

from config import Settings

settings = Settings.from_env()

bind = f"{settings.api_host}:{settings.api_port}"
workers = 1
worker_class = "gthread"
threads = settings.web_threads
timeout = 120
graceful_timeout = 30
keepalive = 5
max_requests = 0

# Runtime files must be writable even with a read-only container root.
worker_tmp_dir = "/tmp"
control_socket_disable = True

accesslog = "-"
errorlog = "-"
loglevel = settings.log_level
access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s '
    '"%(f)s" "%(a)s"'
)

# Do not trust X-Forwarded-For from arbitrary clients. Enable
# TRUST_PROXY_HEADERS only behind a proxy that overwrites the header.
forwarded_allow_ips = ""

preload_app = False
