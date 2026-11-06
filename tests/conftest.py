"""Shared fixtures for the ziv suite.

The suite never sleeps for real time: anything that waits takes a clock, and
tests drive the clock. There is no sys.path manipulation — ``ziv`` is an
installed package (``uv pip install -e .``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT
