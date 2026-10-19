---
name: study-plan-from-job
description: Turn a job description into a study plan on the agile board, linking Scarlet College lessons for each skill gap.
version: 0.9.0
lifecycle: beta
owner: platform@scarletbeast.com
tags: [agile, college, rag, writes]
aliases:
  - study plan for this job
  - prepare me for this role
allowed_tools:
  - college-mcp:search_lessons
  - college-mcp:get_lesson
  - agile-mcp:list_tasks
  - agile-mcp:create_task
preflight:
  - name: job_description
    description: The job description text.
    required: true
  - name: known_skills
    description: Comma-separated skills the student already has, to skip.
    required: false
  - name: project
    description: Board project key to put the study tasks in.
    required: false
    default: SB
---
# Study plan from a job description

Reads a job description, finds the skills it requires that the student lacks, finds a Scarlet College
lesson for each, and puts one study task per gap on the board. This is the only skill that writes.

## Workflow

1. Extract at most eight required skills from `job_description`; drop any in `known_skills`.
2. For each skill, call `college-mcp:search_lessons` with the skill as `query`, `k=3`.
3. For each skill whose best result scores 0.55 or more, call `college-mcp:get_lesson` once to get its `url` and `title`.
4. Call `agile-mcp:list_tasks` with `project` and `label="study"` to find study tasks that already exist.
5. For each skill with no existing task, call `agile-mcp:create_task` with `title="Study: <skill>"`,
   `type="task"`, `labels="study"`, and a `description` listing the lesson title and `url` (or
   "no lesson yet" when nothing scored 0.55).
6. Reply with a table: skill, lesson, task key.

## Errors

| Error | Meaning | Do this |
| --- | --- | --- |
| `invalid_input` from create_task | A field was rejected | Fix that field as the message says and retry once |
| `backend_unavailable` | A backend did not answer | Retry once; then stop and report which tasks were created |
| `forbidden` | Outside this skill's scope, or the token cannot write | Stop; report what was done so far |

## Gotchas

- Never create a task twice: step 4 is what makes re-running the skill safe.
- Keep titles short; the board shows about 60 characters.
- This skill is beta: OPA blocks it in prod until it is promoted to production.
