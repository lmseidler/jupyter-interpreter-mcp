"""Integration tests for list_dir tool."""

import os

import pytest

from jupyter_interpreter_mcp import server
from jupyter_interpreter_mcp.remote import RemoteJupyterClient

REQUIRES_JUPYTER = bool(os.getenv("JUPYTER_BASE_URL") and os.getenv("JUPYTER_TOKEN"))

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.skipif(
    not REQUIRES_JUPYTER,
    reason="JUPYTER_BASE_URL and JUPYTER_TOKEN required for integration tests",
)
async def test_list_dir_with_real_server(monkeypatch):
    """Test list_dir against a real Jupyter server."""
    base_url = os.getenv("JUPYTER_BASE_URL")
    token = os.getenv("JUPYTER_TOKEN")
    if not base_url or not token:
        pytest.skip("JUPYTER_BASE_URL and JUPYTER_TOKEN required")

    client = RemoteJupyterClient(base_url=base_url, auth_token=token)

    monkeypatch.setattr(server, "remote_client", client, raising=False)

    result = await server.list_dir()
    print(result)

    assert result["error"] == ""
    assert isinstance(result["result"], list)
    assert result["result"]
    for line in result["result"]:
        assert isinstance(line, str)
        assert line.startswith(
            ("file ", "directory ", "notebook ", "(empty directory)")
        )
