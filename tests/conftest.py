from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from filigrane_api.main import app


@pytest.fixture
def sync_client() -> Generator[TestClient, None, None]:
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
