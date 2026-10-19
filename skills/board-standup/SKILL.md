---
name: board-standup
description: Summarise what is in progress, blocked and next on an agile board, for a daily standup.
version: 1.0.0
lifecycle: production
owner: platform@scarletbeast.com
tags: [agile, reporting, read-only]
aliases:
  - standup
  - what's on the board
  - daily standup summary
allowed_tools:
  - agile-mcp:bootstrap_guide
  - agile-mcp:list_tasks
  - agile-mcp:get_task
preflight:
  - name: project
    description: Board project key, such as SB.
    required: false
    default: SB
---
# Board standup

Produces a short standup summary for one project: in progress, in review, blocked, and the next three
to pick up. Read-only: this skill never changes the board.

## Workflow

1. Call `agile-mcp:list_tasks` with `project` and `status="in_progress,review"`.
2. Call `agile-mcp:list_tasks` with `project` and `status="todo"`, `limit=10`.
3. For any in-progress task whose labels include `blocked`, call `agile-mcp:get_task` and read its latest comment.
4. Reply with four short lists: In progress, In review, Blocked (with the reason), Next up (top three todo by priority).

## Errors

| Error | Meaning | Do this |
| --- | --- | --- |
| `not_found` | The project key does not exist | Call `agile-mcp:bootstrap_guide`, then ask the user for the right key |
| `backend_unavailable` | The board did not answer | Retry once; then stop and say the board is down |
| `forbidden` | The call is outside this skill's scope | Stop; do not try other tools |

## Gotchas

- `list_tasks` leaves out done tasks unless `status` asks for them; that is what a standup wants.
- Task keys look like `SB-12`; never pass a title to `get_task`.
