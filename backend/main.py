"""Backward-compatible Render entry point: uvicorn main:app."""

from app.main import app


__all__ = ["app"]
