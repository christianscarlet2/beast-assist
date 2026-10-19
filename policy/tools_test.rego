package beast.tools_test

import rego.v1

import data.beast.tools

skills := {
	"board-standup": {"lifecycle": "production", "allowed_tools": ["agile-mcp:list_tasks", "agile-mcp:get_task"]},
	"study-plan": {"lifecycle": "beta", "allowed_tools": ["agile-mcp:create_task", "college-mcp:search_lessons"]},
}

reader := {"oid": "u1", "permissions": ["Tools.Read"]}

writer := {"oid": "u2", "permissions": ["Tools.Read", "Tools.Write"]}

call(skill, tool, write, subject, env) := {
	"env": env, "skill": skill, "qualified_tool": tool, "write": write, "subject": subject,
}

test_allowed_read if {
	tools.allow with input as call("board-standup", "agile-mcp:list_tasks", false, reader, "prod")
		with data.beast.skills as skills
}

test_tool_outside_allowed_tools_denied if {
	not tools.allow with input as call("board-standup", "agile-mcp:create_task", true, writer, "prod")
		with data.beast.skills as skills
}

test_write_needs_write_permission if {
	not tools.allow with input as call("study-plan", "agile-mcp:create_task", true, reader, "dev")
		with data.beast.skills as skills
	tools.allow with input as call("study-plan", "agile-mcp:create_task", true, writer, "dev")
		with data.beast.skills as skills
}

test_beta_skill_blocked_in_prod if {
	not tools.allow with input as call("study-plan", "college-mcp:search_lessons", false, reader, "prod")
		with data.beast.skills as skills
	d := tools.decision with input as call("study-plan", "college-mcp:search_lessons", false, reader, "prod")
		with data.beast.skills as skills
	"skill \"study-plan\" is beta and cannot run in prod" in d.reasons
}

test_unknown_skill_denied if {
	not tools.allow with input as call("nope", "agile-mcp:list_tasks", false, reader, "dev")
		with data.beast.skills as skills
}

test_missing_skill_header_reason if {
	d := tools.decision with input as call("", "agile-mcp:list_tasks", false, reader, "dev")
		with data.beast.skills as skills
	"no skill named in the X-Skill-Id header" in d.reasons
}
