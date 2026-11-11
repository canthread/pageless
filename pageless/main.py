"""ASGI entry point: `uvicorn pageless.main:app`."""

from .app import create_app

app = create_app()
