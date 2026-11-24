"""Production WSGI entrypoint used by Gunicorn.

Run with a single worker and multiple threads so the Discord Gateway is opened
once while Flask-Sock can still serve concurrent WebSocket connections:

    gunicorn --config gunicorn.conf.py wsgi:app
"""

import logging

from main import (
    SETTINGS,
    app,
    initialize_database,
    start_gateway_thread,
    validate_startup_configuration,
)

logging.basicConfig(
    level=getattr(logging, SETTINGS.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

validate_startup_configuration()
initialize_database()
start_gateway_thread()

__all__ = ["app"]
