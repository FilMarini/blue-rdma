"""Pytest configuration for the bsc2vhdl unit suite.

Inserts the repository root at the front of `sys.path` so `from
tools.bsc2vhdl import ...` resolves regardless of the working directory the
test runner was invoked from.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def vendor_dir() -> Path:
    return Path(__file__).resolve().parent / "vendor"


@pytest.fixture
def vendor_rdma_dir() -> Path:
    return Path(__file__).resolve().parent / "vendor_rdma"
