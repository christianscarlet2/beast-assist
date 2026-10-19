"""The coordinator against the running stack (make up && make seed), with a scripted model."""
import pytest

from agent.coordinator import build
from agent.model import ScriptedModel

pytestmark = pytest.mark.integration


async def test_standup_runs_with_only_its_tools():
    model = ScriptedModel(steps=[{"tool": "list_tasks", "args": {"project": "SB", "status": "in_progress,review"}},
                                 {"say": "In progress: ..."}])
    out = await build(model).ainvoke({"request": "give me the daily standup summary", "inputs": {}})
    assert out["skill"]["name"] == "board-standup"
    assert out["inputs"]["project"] == "SB"                    # default filled by preflight
    assert [c["tool"] for c in out["tool_calls"]] == ["list_tasks"]
    tool_msgs = [m for m in out["messages"] if m.type == "tool"]
    assert tool_msgs and "forbidden" not in str(tool_msgs[0].content) and "unauthorized" not in str(tool_msgs[0].content)


async def test_missing_required_input_asks_instead_of_running():
    out = await build(ScriptedModel(steps=[{"say": "x"}])).ainvoke(
        {"request": "prepare me for this role", "inputs": {}})
    assert out["skill"]["name"] == "study-plan-from-job"
    assert "job_description" in out["answer"] and not out.get("tool_calls")


async def test_tutor_retrieves_from_the_college():
    model = ScriptedModel(steps=[{"tool": "search_lessons", "args": {"query": "FastAPI dependency overrides", "k": 3}},
                                 {"say": "answer"}])
    out = await build(model).ainvoke({"request": "tutor me on FastAPI dependencies",
                                      "inputs": {"question": "FastAPI dependency overrides"}})
    assert out["skill"]["name"] == "college-tutor"
    assert "FastAPI" in str([m.content for m in out["messages"] if m.type == "tool"])
