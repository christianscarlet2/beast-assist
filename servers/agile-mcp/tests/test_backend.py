"""The board's real error shapes map to the codes skills' error tables use."""
import importlib.util
from pathlib import Path

import httpx
import pytest

from beast_mcp import ToolFailure

spec = importlib.util.spec_from_file_location("agile_backend_under_test", Path(__file__).parents[1] / "src/backend.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def backend(status, body):
    return mod.AgileBackend("https://board.test/api/agile", "t", "test",
                            transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)))


@pytest.mark.parametrize("status,body,code", [
    (404, {"error": "gone"}, "not_found"),
    (422, {"error": "No task 'SB-999999'."}, "not_found"),          # what the live board actually returns
    (422, {"error": "The title field is required."}, "invalid_input"),
    (500, {"error": "boom"}, "backend_error"),
])
async def test_error_mapping(status, body, code):
    with pytest.raises(ToolFailure) as e:
        await backend(status, body).call("GET", "/tasks/SB-1")
    assert e.value.code == code


async def test_sends_token_and_actor():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(200, json=[])
    b = mod.AgileBackend("https://board.test/api/agile", "secret-token", "Beast Assist (MCP)",
                         transport=httpx.MockTransport(handler))
    await b.call("GET", "/projects")
    assert seen["authorization"] == "Bearer secret-token" and seen["x-agile-actor"] == "Beast Assist (MCP)"
