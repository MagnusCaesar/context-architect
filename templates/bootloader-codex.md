### Codex

This managed `AGENTS.md` block is session-scoped. After bootstrap or refresh, start a new Codex session before relying on changed instructions or hooks.

Use bounded local commands for repository analysis. Keep task coordination in the active task scope.

With the default profiles, use `balanced` (GPT-6 Sol) for routine implementation and
coordination, and `economy` (GPT-6 Luna) for bounded research or inventory.
Select `lead` (GPT-6 Astra) only when the user explicitly requests Astra.
Preserve explicit user model choices; do not escalate to Astra automatically.
Existing project profiles may retain other explicitly configured model pins.

<!-- context-architecture:end -->
