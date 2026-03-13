"""Integration test for session restoration against a real Jupyter server."""

import os
import uuid

import pytest

from jupyter_interpreter_mcp.notebook import Notebook
from jupyter_interpreter_mcp.remote import RemoteJupyterClient

REQUIRES_JUPYTER = bool(os.getenv("JUPYTER_BASE_URL") and os.getenv("JUPYTER_TOKEN"))

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.skipif(
    not REQUIRES_JUPYTER,
    reason="JUPYTER_BASE_URL and JUPYTER_TOKEN required for integration tests",
)
async def test_session_restoration_with_real_server() -> None:
    """Ensure restored sessions rehydrate variables across kernel restarts."""
    base_url = os.getenv("JUPYTER_BASE_URL")
    token = os.getenv("JUPYTER_TOKEN")
    if not base_url or not token:
        pytest.skip("JUPYTER_BASE_URL and JUPYTER_TOKEN required")

    client = RemoteJupyterClient(base_url=base_url, auth_token=token)
    session_dir = f"/home/jovyan/jupyter-interpreter-mcp-tests/{uuid.uuid4()}"

    # Ensure the session directory exists on the remote side before
    # dump_to_file/load_from_file use the Contents API.
    api_session_dir = client._to_api_path(session_dir)
    client.create_directory(api_session_dir)

    notebook1 = Notebook("restore-test-1", client, session_dir)
    notebook2 = Notebook("restore-test-2", client, session_dir)
    notebook3 = Notebook("restore-test-3", client, session_dir)

    await notebook1.connect()
    await notebook2.connect()
    await notebook3.connect()

    try:
        first = await notebook1.execute_new_code("value = 41")
        assert first["error"] == []
        second = await notebook1.execute_new_code("answer = value + 1")
        assert second["error"] == []
        await notebook1.dump_to_file()
        notebook1.close()

        restored = await notebook2.load_from_file()
        assert restored is True
        check_answer = await notebook2.execute_new_code("print(answer)")
        assert check_answer["error"] == []
        assert "42" in "".join(check_answer["result"])
        next_value = await notebook2.execute_new_code("next_answer = answer + 1")
        assert next_value["error"] == []
        await notebook2.dump_to_file()
        notebook2.close()

        restored_again = await notebook3.load_from_file()
        assert restored_again is True
        check_next = await notebook3.execute_new_code("print(next_answer)")
        assert check_next["error"] == []
        assert "43" in "".join(check_next["result"])
    finally:
        notebook1.close()
        notebook2.close()
        notebook3.close()
        cleanup_kernel_id = client.create_kernel()
        try:
            cleanup = await client.execute(
                cleanup_kernel_id,
                f"""
import shutil
shutil.rmtree({repr(session_dir)}, ignore_errors=True)
""",
            )
            assert cleanup["error"] == []
        finally:
            client.shutdown_kernel(cleanup_kernel_id)
