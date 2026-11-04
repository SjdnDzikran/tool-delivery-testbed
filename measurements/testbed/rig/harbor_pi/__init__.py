"""Pinned Harbor 0.23.0 / Pi 1.0.4 integration, under validation [ours]."""
from importlib.metadata import version

if version("harbor") != "0.23.0":
    raise RuntimeError("This adapter requires exactly Harbor 0.23.0")
