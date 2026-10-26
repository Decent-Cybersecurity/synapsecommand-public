"""Fixtures for the host's tests. Nothing here touches the network, the clock or the checkout:
every store lives under the test's own `tmp_path`."""

from __future__ import annotations

import pytest

from synapse_imagery.assets import LocalAssetStore
from synapse_imagery.fakes import MemoryAssetStore
from synapse_imagery.ingest import IngestService
from synapse_imagery.policy import Principal

LOCAL = Principal("local", "local-operator")


@pytest.fixture
def store(tmp_path):
    return LocalAssetStore(tmp_path / "store")


@pytest.fixture
def memory_store():
    made = MemoryAssetStore()
    try:
        yield made
    finally:
        made.close()


@pytest.fixture
def services():
    """A factory of ingest services; every one is closed (its pool's children killed) after."""
    made = []

    def build(store, **options):
        service = IngestService(store, **options)
        made.append(service)
        return service

    try:
        yield build
    finally:
        for service in made:
            service.close()
