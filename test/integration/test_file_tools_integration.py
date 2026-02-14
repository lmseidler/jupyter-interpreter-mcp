"""Integration tests for upload_file_path and get_sandbox_path tools."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from jupyter_interpreter_mcp import server
from jupyter_interpreter_mcp.remote import RemoteJupyterClient

REQUIRES_JUPYTER = bool(os.getenv("JUPYTER_BASE_URL") and os.getenv("JUPYTER_TOKEN"))

pytestmark = pytest.mark.integration


async def _ensure_session(monkeypatch):
    """Create a session and return the session_id.

    Sets up the ``server.remote_client`` and creates a new session via
    ``server.create_session``.
    """
    base_url = os.getenv("JUPYTER_BASE_URL")
    token = os.getenv("JUPYTER_TOKEN")
    if not base_url or not token:
        pytest.skip("JUPYTER_BASE_URL and JUPYTER_TOKEN required")

    client = RemoteJupyterClient(base_url=base_url, auth_token=token)
    monkeypatch.setattr(server, "remote_client", client, raising=False)

    result = await server.create_session()
    assert "error" not in result or result.get("error") == ""
    session_id = result["session_id"]
    return session_id


@pytest.mark.asyncio
@pytest.mark.skipif(
    not REQUIRES_JUPYTER,
    reason="JUPYTER_BASE_URL and JUPYTER_TOKEN required for integration tests",
)
async def test_large_file_upload_streaming(monkeypatch):
    """8.1 - Large file upload (>100MB) to verify chunked streaming.

    Creates a 100+ MB file on the host and uploads it to the sandbox,
    confirming the file arrives intact via size comparison.
    """
    session_id = await _ensure_session(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a 101 MB file filled with repeating bytes
        large_file = Path(tmpdir) / "large_test_file.bin"
        chunk = b"X" * (1024 * 1024)  # 1 MB
        with open(large_file, "wb") as f:
            for _ in range(101):
                f.write(chunk)

        host_file_size = large_file.stat().st_size
        assert host_file_size > 100 * 1024 * 1024

        with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
            result = await server.upload_file_path(
                session_id=session_id,
                host_path=str(large_file),
                destination_path="large_test_file.bin",
            )

        assert "error" not in result, f"Upload failed: {result.get('error')}"
        assert result["status"] == "success"
        assert result["size"] == str(host_file_size)

        # Verify the file exists in the sandbox via get_sandbox_path
        path_result = await server.get_sandbox_path(
            session_id=session_id,
            file_path="large_test_file.bin",
        )
        assert (
            "error" not in path_result
        ), f"get_sandbox_path failed: {path_result.get('error')}"
        assert path_result["size"] == str(host_file_size)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not REQUIRES_JUPYTER,
    reason="JUPYTER_BASE_URL and JUPYTER_TOKEN required for integration tests",
)
async def test_end_to_end_workflow(monkeypatch):
    """8.2 - End-to-end workflow using both new tools.

    Uploads a file via ``upload_file_path``, then retrieves its metadata
    via ``get_sandbox_path`` and verifies consistency.
    """
    session_id = await _ensure_session(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "workflow_test.txt"
        test_content = "Integration test content\nLine 2\n"
        test_file.write_text(test_content)

        host_file_size = test_file.stat().st_size

        with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
            upload_result = await server.upload_file_path(
                session_id=session_id,
                host_path=str(test_file),
                destination_path="workflow_test.txt",
            )

        assert (
            "error" not in upload_result
        ), f"Upload failed: {upload_result.get('error')}"
        assert upload_result["status"] == "success"
        sandbox_path = upload_result["sandbox_path"]

        # Now retrieve the file metadata
        path_result = await server.get_sandbox_path(
            session_id=session_id,
            file_path="workflow_test.txt",
        )

        assert (
            "error" not in path_result
        ), f"get_sandbox_path failed: {path_result.get('error')}"
        assert path_result["sandbox_path"] == sandbox_path
        assert path_result["size"] == str(host_file_size)
        assert "last_modified" in path_result
        # last_modified should be a valid timestamp (positive float)
        assert float(path_result["last_modified"]) > 0


@pytest.mark.asyncio
@pytest.mark.skipif(
    not REQUIRES_JUPYTER,
    reason="JUPYTER_BASE_URL and JUPYTER_TOKEN required for integration tests",
)
async def test_overwrite_protection_workflow(monkeypatch):
    """8.3 - Overwrite protection workflow.

    Uploads a file, then attempts to upload again with ``overwrite=False``
    to confirm it is rejected, and with ``overwrite=True`` to confirm it
    succeeds.
    """
    session_id = await _ensure_session(monkeypatch)

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "overwrite_test.txt"
        test_file.write_text("original content")

        with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": tmpdir}):
            # First upload — should succeed
            result1 = await server.upload_file_path(
                session_id=session_id,
                host_path=str(test_file),
                destination_path="overwrite_test.txt",
            )
            assert (
                "error" not in result1
            ), f"First upload failed: {result1.get('error')}"

            # Second upload with overwrite=False — should fail
            result2 = await server.upload_file_path(
                session_id=session_id,
                host_path=str(test_file),
                destination_path="overwrite_test.txt",
                overwrite=False,
            )
            assert "error" in result2
            assert "already exists" in result2["error"]

            # Third upload with overwrite=True — should succeed
            test_file.write_text("updated content")
            result3 = await server.upload_file_path(
                session_id=session_id,
                host_path=str(test_file),
                destination_path="overwrite_test.txt",
                overwrite=True,
            )
            assert (
                "error" not in result3
            ), f"Overwrite upload failed: {result3.get('error')}"
            assert result3["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not REQUIRES_JUPYTER,
    reason="JUPYTER_BASE_URL and JUPYTER_TOKEN required for integration tests",
)
async def test_path_security_enforcement(monkeypatch):
    """8.4 - Path security enforcement.

    Verifies that:
    - Uploading from outside allowed directories is rejected.
    - Uploading a sensitive file (.env) is rejected.
    - Path traversal in destination_path is rejected.
    """
    session_id = await _ensure_session(monkeypatch)

    with tempfile.TemporaryDirectory() as allowed_dir:
        with tempfile.TemporaryDirectory() as outside_dir:
            # Create a file outside allowed directories
            outside_file = Path(outside_dir) / "outside.txt"
            outside_file.write_text("should be blocked")

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": allowed_dir}):
                # Test: file outside allowed dirs
                result = await server.upload_file_path(
                    session_id=session_id,
                    host_path=str(outside_file),
                    destination_path="outside.txt",
                )
                assert "error" in result
                assert "outside allowed" in result["error"]

            # Create a sensitive file inside allowed dirs
            env_file = Path(allowed_dir) / ".env"
            env_file.write_text("SECRET=abc123")

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": allowed_dir}):
                # Test: sensitive file
                result = await server.upload_file_path(
                    session_id=session_id,
                    host_path=str(env_file),
                    destination_path=".env",
                )
                assert "error" in result
                assert "sensitive" in result["error"].lower()

            # Create a normal file for path traversal test
            normal_file = Path(allowed_dir) / "normal.txt"
            normal_file.write_text("normal content")

            with patch.dict("os.environ", {"ALLOWED_UPLOAD_DIRS": allowed_dir}):
                # Test: path traversal in destination
                result = await server.upload_file_path(
                    session_id=session_id,
                    host_path=str(normal_file),
                    destination_path="../../../etc/passwd",
                )
                assert "error" in result
                assert "escapes session directory" in result["error"]
