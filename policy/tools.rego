# Tool-call authorization for Beast Assist MCP servers.
#
# data.beast.skills is the Skills Registry, delivered to OPA as a bundle:
#   {"<skill>": {"allowed_tools": ["agile-mcp:list_tasks", ...], "lifecycle": "production", ...}}
# A call is allowed only when ALL hold:
#   1. the call names a registered skill
#   2. the skill's lifecycle stage may run in this environment
#   3. the skill's allowed_tools lists this exact server:tool
#   4. the caller's token carries Tools.Read, and Tools.Write for a tool that changes a backend
package beast.tools

import rego.v1

default allow := false

skill := data.beast.skills[input.skill]

stages := {
	"dev": {"draft", "beta", "production"},
	"staging": {"beta", "production"},
	"prod": {"production"},
}

needed contains "Tools.Read"

needed contains "Tools.Write" if input.write

missing contains p if {
	some p in needed
	not p in input.subject.permissions
}

allow if {
	skill
	skill.lifecycle in stages[input.env]
	input.qualified_tool in skill.allowed_tools
	count(missing) == 0
}

reasons contains "no skill named in the X-Skill-Id header" if input.skill == ""

reasons contains sprintf("skill %q is not in the registry", [input.skill]) if {
	input.skill != ""
	not data.beast.skills[input.skill]
}

reasons contains sprintf("skill %q is %s and cannot run in %s", [input.skill, skill.lifecycle, input.env]) if {
	not skill.lifecycle in stages[input.env]
}

reasons contains sprintf("%s is not in the allowed_tools of skill %q", [input.qualified_tool, input.skill]) if {
	skill
	not input.qualified_tool in skill.allowed_tools
}

reasons contains sprintf("token lacks %s", [p]) if some p in missing

decision := {"allow": allow, "reasons": [r | some r in reasons]}
