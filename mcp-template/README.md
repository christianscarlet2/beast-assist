# template-mcp

A single-platform MCP tool server: ONE backend, one tool per file.

    src/backend.py        make_backend() -> the one client for the backend (async, with ready() and aclose())
    src/tools/<tool>.py   one @tool function each; files starting with _ are skipped
    src/main.py           app = create_app(...)
    tests/                unit tests against a fake backend, integration tests against the real one

Conventions (enforced by review and by audit_skill_config.py):
- Tools are list_* / get_* / create_* style, single-purpose, with a one-paragraph docstring the model reads.
- Return small dicts and lists, not raw backend payloads; never return secrets.
- Raise ToolFailure(message, hint, code) for anything the agent can act on; codes: not_found,
  invalid_input, not_ready, backend_unavailable, backend_error.
- Mark tools that change the backend @tool(write=True): they need Tools.Write and an explicit grant.
- Ship a bootstrap_guide tool: what the server covers, vocabulary, which tool to call first.
