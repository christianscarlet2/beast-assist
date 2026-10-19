"""Beast Assist coordinator: a LangGraph supervisor that turns a request into a governed skill run.

    resolve_skill -> preflight -> run_specialist -> report
                         |
                         +-> ask_user (a required input is missing)

resolve_skill  asks the Skills Registry which skill fits the request (aliases first).
preflight      checks the skill's declared inputs; a missing required one stops the run with a question.
run_specialist a ReAct agent whose system prompt is the skill's workflow and whose tools are ONLY the
               skill's allowed_tools, loaded over MCP with the agent's Entra token and X-Skill-Id, so the
               servers and OPA enforce the same scope again on every call.
"""
import json
import os
from typing import Any, TypedDict

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

from .mcp_tools import load_tools

REGISTRY = os.environ.get("REGISTRY_URL", "http://localhost:8410").rstrip("/")
SERVERS = json.loads(os.environ.get("MCP_SERVERS", json.dumps({
    "agile-mcp": "http://localhost:8421/mcp", "college-mcp": "http://localhost:8422/mcp"})))


class State(TypedDict, total=False):
    request: str
    inputs: dict
    skill: dict
    missing: list
    messages: list
    tool_calls: list
    answer: str


def agent_token() -> str:
    """Client-credentials token for the agent's own app registration (Entra, or the dev issuer)."""
    r = httpx.post(os.environ.get("TOKEN_URL", "http://localhost:8400/beast-dev-tenant/oauth2/v2.0/token"), data={
        "grant_type": "client_credentials", "client_id": os.environ.get("AGENT_CLIENT_ID", "beast-agent"),
        "client_secret": os.environ.get("AGENT_CLIENT_SECRET", "dev-agent-secret"),
        "scope": os.environ.get("AUTH_AUDIENCE", "api://beast-assist") + "/.default"}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def build(model, token: str | None = None):
    async def resolve_skill(s: State) -> State:
        async with httpx.AsyncClient(timeout=10) as c:
            name = (s.get("inputs") or {}).get("skill")
            if name:
                r = await c.get(f"{REGISTRY}/skills/{name}")
            else:
                r = await c.get(f"{REGISTRY}/resolve", params={"q": s["request"]})
                if r.status_code == 200:
                    r = await c.get(f"{REGISTRY}/skills/{r.json()['skill']['name']}")
        if r.status_code != 200:
            return {"answer": f"No skill fits that request ({r.json().get('detail')}).", "skill": {}}
        return {"skill": r.json()}

    def preflight(s: State) -> State:
        inputs = dict(s.get("inputs") or {})
        missing = []
        for p in s["skill"].get("preflight", []):
            if p["name"] not in inputs:
                if p.get("default") is not None:
                    inputs[p["name"]] = p["default"]
                elif p.get("required"):
                    missing.append(p)
        return {"inputs": inputs, "missing": missing}

    def ask_user(s: State) -> State:
        need = "; ".join(f"{p['name']}: {p['description']}" for p in s["missing"])
        return {"answer": f"Before I run {s['skill']['name']}, I need: {need}"}

    async def run_specialist(s: State) -> State:
        sk = s["skill"]
        tok = token or agent_token()
        servers = sorted({t.split(":")[0] for t in sk["allowed_tools"]})
        headers = {"Authorization": f"Bearer {tok}", "X-Skill-Id": sk["name"]}
        tools = []
        for srv in servers:
            # the servers already filter tools/list to the skill's scope; filter again so a misconfigured
            # server can never widen it
            allowed = {t.split(":")[1] for t in sk["allowed_tools"] if t.startswith(srv + ":")}
            tools += await load_tools(srv, SERVERS[srv], headers, allowed)
        system = (f"You are running the skill '{sk['name']}' ({sk['description']}).\n"
                  f"Follow its workflow exactly. Tool names in the workflow are written server:tool; call the "
                  f"tool by the part after the colon.\n\n{sk['body']}\n\nInputs: {json.dumps(s['inputs'])}")
        agent = create_react_agent(model, tools)
        out = await agent.ainvoke({"messages": [SystemMessage(system), HumanMessage(s["request"])]},
                                  {"recursion_limit": 40})
        calls = [{"tool": tc["name"], "args": tc["args"]} for m in out["messages"]
                 for tc in (getattr(m, "tool_calls", None) or [])]
        return {"messages": out["messages"], "tool_calls": calls, "answer": out["messages"][-1].content}

    g = StateGraph(State)
    g.add_node("resolve_skill", resolve_skill)
    g.add_node("preflight", preflight)
    g.add_node("ask_user", ask_user)
    g.add_node("run_specialist", run_specialist)
    g.set_entry_point("resolve_skill")
    g.add_conditional_edges("resolve_skill", lambda s: "preflight" if s.get("skill") else END)
    g.add_conditional_edges("preflight", lambda s: "ask_user" if s["missing"] else "run_specialist")
    g.add_edge("ask_user", END)
    g.add_edge("run_specialist", END)
    return g.compile()


async def run(request: str, inputs: dict | None = None, model: Any = None) -> State:
    from .model import bedrock_model
    graph = build(model or bedrock_model())
    return await graph.ainvoke({"request": request, "inputs": inputs or {}})


if __name__ == "__main__":
    import asyncio
    import sys
    if len(sys.argv) < 2:
        sys.exit('usage: python -m agent.coordinator "<request>" [key=value ...]')
    kv = dict(a.split("=", 1) for a in sys.argv[2:])
    result = asyncio.run(run(sys.argv[1], kv))
    print(result.get("answer"))
    for c in result.get("tool_calls", []):
        print("  called", c["tool"], json.dumps(c["args"])[:120])
