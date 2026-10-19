"""The platform's guarantees, end to end over MCP HTTP: auth, skill scope, write gating, lifecycle,
tools/list filtering, error mapping, health."""
import httpx
import pytest

from conftest import make_token, mcp_call


class FakeAgile:
    def __init__(self):
        self.calls = []

    async def call(self, method, path, body=None, params=None):
        self.calls.append((method, path, body, params))
        if method == "GET" and path == "/tasks":
            return [{"key": "SB-1", "title": "Ship it", "status": "todo", "secret_field": "x"}]
        if method == "GET" and path == "/tasks/SB-404":
            from beast_mcp import ToolFailure
            raise ToolFailure("no task SB-404", hint="check the key with list_tasks", code="not_found")
        if method == "POST" and path == "/tasks":
            return {"key": "SB-2", "title": body["title"], "status": "backlog"}
        return {}

    async def ready(self):
        return True


@pytest.fixture
def agile(serve):
    fake = FakeAgile()
    return serve("agile-mcp", fake), fake


async def test_read_tool_with_valid_token(agile):
    base, fake = agile
    err, out = await mcp_call(base, "list_tasks", {"project": "SB"}, skill="board-standup", token=make_token())
    assert not err
    assert out == [{"key": "SB-1", "type": None, "title": "Ship it", "status": "todo", "priority": None,
                    "points": None, "assignee": None, "labels": None, "due_date": None}]
    assert "secret_field" not in str(out)  # tools return slim rows, not raw payloads


@pytest.mark.parametrize("tok,why", [
    (None, "missing bearer token"),
    (make_token(aud="api://someone-else"), "invalid token"),
    (make_token(iss="https://evil.example/v2.0"), "invalid token"),
    (make_token(exp_in=-10), "invalid token"),
], ids=["no-token", "wrong-audience", "wrong-issuer", "expired"])
async def test_bad_tokens_are_refused(agile, tok, why):
    base, fake = agile
    err, out = await mcp_call(base, "list_tasks", skill="board-standup", token=tok)
    assert err and "unauthorized" in out and why in out
    assert fake.calls == []  # never reached the backend


async def test_tool_outside_skill_scope_is_forbidden(agile):
    base, fake = agile
    err, out = await mcp_call(base, "create_task", {"title": "x"}, skill="board-standup",
                              token=make_token(["Tools.Read", "Tools.Write"]))
    assert err and "not in the allowed_tools" in out
    assert fake.calls == []


async def test_write_needs_write_role(agile):
    base, fake = agile
    err, out = await mcp_call(base, "create_task", {"title": "Study: OPA", "labels": "study"},
                              skill="study-plan-from-job", token=make_token())
    assert err and "token lacks Tools.Write" in out
    err, out = await mcp_call(base, "create_task", {"title": "Study: OPA", "labels": "study"},
                              skill="study-plan-from-job", token=make_token(["Tools.Read", "Tools.Write"]))
    assert not err and out["key"] == "SB-2"


async def test_beta_skill_blocked_in_prod(serve):
    base = serve("agile-mcp", FakeAgile(), env="prod")
    err, out = await mcp_call(base, "list_tasks", skill="study-plan-from-job", token=make_token())
    assert err and "is beta and cannot run in prod" in out


async def test_no_skill_header(agile):
    base, _ = agile
    err, out = await mcp_call(base, "list_tasks", token=make_token())
    assert err and "X-Skill-Id" in out


async def test_tools_list_is_filtered_to_the_skill(agile):
    base, _ = agile
    _, names = await mcp_call(base, None, skill="board-standup", token=make_token(), list_tools=True)
    assert names == ["bootstrap_guide", "get_task", "list_tasks"]
    _, names = await mcp_call(base, None, skill="study-plan-from-job", token=make_token(), list_tools=True)
    assert names == ["create_task", "list_tasks"]


async def test_backend_failure_reaches_the_agent_with_a_hint(agile):
    base, _ = agile
    err, out = await mcp_call(base, "get_task", {"key": "SB-404"}, skill="board-standup", token=make_token())
    assert err and "not_found: no task SB-404" in out and "Next: check the key" in out


async def test_input_validated_before_backend(agile):
    base, fake = agile
    err, out = await mcp_call(base, "get_task", {"key": "nonsense"}, skill="board-standup", token=make_token())
    assert err and "invalid_input" in out and fake.calls == []


async def test_health_endpoints(agile):
    base, _ = agile
    async with httpx.AsyncClient() as c:
        h = (await c.get(base + "/healthz")).json()
        assert h["ok"] and h["tools"] == 6
