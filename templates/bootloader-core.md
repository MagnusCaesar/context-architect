<!-- context-architecture:start -->
## Context Architecture

This repository has a deterministic local context architecture under `context/`.

### FIRST STEP — READ CONTEXT BEFORE ANY PROJECT WORK

Read the map + control plane cheaply (body-only, no lock/infra noise):

```
python3 context/scripts/extract-body.py context/index.html context/control-plane.html
```

Read further `context/*.html` pages the same way. `extract-body.py` strips head/tags and keeps links as `text (href)`. Do not raw-read context HTML; that burns tokens on infrastructure you do not need.

Any project work requires reading the map + control plane first. This includes touching project files or answering questions about their code, domain, files, or behavior. Skip this only for genuinely unrelated questions.

### READING CONTEXT — KEEP IT CHEAP

- Context pages: use `python3 context/scripts/extract-body.py <page.html> ...`.
- For call relationships, query `graphify-out/graph.json` first when it exists.
- Keep other repository analysis bounded; use available local tooling that preserves the task context.

### SOURCE EDIT POLICY

Before changing project source, identify the user's action verb and target. Edits are permitted only when the verb is one of `fix`, `change`, `edit`, `update`, `modify`, `add`, or `remove`, and a file, function, or behavior is named. Otherwise investigate, report the root cause, propose the exact fix, and ask for approval.

Context pages (`context/*.html`) may be updated freely as infrastructure.

### ACTIVE HARNESS — CAPTURE PROTOCOL

After an exchange changes state, update context: decisions go to `decisions/`, unresolved questions to `open-questions.html`, failures to `failure-todos.html`, and new files or directories to `file-inventory.html`. Store verbatim pasted material under `context/archived/`; context pages hold extracted facts and links.

### WORKFLOW

In the main session, hooks handle routine lock, ledger, and validation work. If a hook reports a failure, repair the named prerequisite before continuing.

### RULES

- HTML under `context/` is source of truth; `docs/context/` is generated projection.
- `<meta name="tracks">` owns source freshness. Missing tracks do not justify scanning the repo.
- Ledger is audit history. Durable knowledge belongs in wiki pages and decisions.
- Unknown agents default to `worker`; map them to `readonly` in `agentRoles` to deny writes.
