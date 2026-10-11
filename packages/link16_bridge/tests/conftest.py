"""Fixtures for the bridge's tests. `h` is a running `helpers.Harness`, closed after the test."""
from __future__ import annotations

import pytest

from helpers import Harness


@pytest.fixture
def h(tmp_path):
    harness = Harness(tmp_path)
    try:
        yield harness
    finally:
        harness.close()


@pytest.fixture
def make_harness(tmp_path):
    """A factory for harnesses with their own options; every one is closed after the test."""
    made = []

    def build(**options):
        sub = tmp_path / f"h{len(made)}"
        sub.mkdir()
        harness = Harness(sub, **options)
        made.append(harness)
        return harness

    try:
        yield build
    finally:
        for harness in made:
            harness.close()
