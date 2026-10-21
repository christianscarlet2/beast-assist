---
name: college-tutor
description: Answer a study question from Scarlet College lessons, citing the lessons it used.
version: 1.1.1
lifecycle: production
owner: college@scarletbeast.com
tags: [college, rag, read-only]
aliases:
  - explain
  - tutor me
  - what does the college say about
allowed_tools:
  - college-mcp:bootstrap_guide
  - college-mcp:list_courses
  - college-mcp:search_lessons
  - college-mcp:get_lesson
preflight:
  - name: question
    description: What the student wants to understand.
    required: true
    from_request: true
  - name: course
    description: Limit the search to one course key (optional).
    required: false
---
# College tutor

Answers from the college's own lessons (retrieval-augmented generation), not from memory, and links
each lesson it drew on.

## Workflow

1. Call `college-mcp:search_lessons` with `query=question` (and `course` if given), `k=5`.
2. If the best `score` is below 0.55, call `college-mcp:list_courses` and tell the user which course
   would cover it; do not answer from memory.
3. Otherwise call `college-mcp:get_lesson` on the top one or two distinct `lesson_id`s.
4. Answer in plain words using only those passages, then list each lesson used with its title and `url`.

## Errors

| Error | Meaning | Do this |
| --- | --- | --- |
| `backend_unavailable` from search | The vector index is down | Call `college-mcp:list_courses` and say search is unavailable |
| `not_ready` | The lesson is still being written | Use the next search result |
| `forbidden` | Outside this skill's scope | Stop |

## Gotchas

- Search is semantic: rephrase the question as a statement of the topic for better matches.
- The same lesson can return several passages; open each lesson once.
