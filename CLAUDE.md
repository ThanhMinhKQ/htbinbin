# Bin Bin Hotel Management System

# AI Engineering Operating System

## Priority Order

1. Preserve security and permissions.
2. Preserve reservation and inventory integrity.
3. Preserve existing business logic.
4. Preserve execution flow stability.
5. Preserve UI/UX consistency.
6. Improve code quality only when directly related.

## Mission

Bin Bin Hotel Management System handles:

- PMS reservations.
- OTA booking ingestion.
- Room inventory and pricing.
- CRM workflows.
- Operational hotel management flows.
- HR attendance, tasks, and lost-and-found workflows.

## Technology Stack

### Backend

- Python.
- FastAPI.
- Starlette.
- Pydantic.
- SQLAlchemy.

### Database

- PostgreSQL.
- Supabase.
- Alembic migrations.

### Frontend

- Jinja templates.
- TailwindCSS.
- Vanilla JavaScript.
- Static assets in `app/static`.

### Jobs & Integrations

- APScheduler.
- Gmail APIs.
- Google APIs.
- OTA workflows.
- Redis/cache support.

### Testing

- pytest.
- Tests under `tests/`.

## Architecture Rules

### Backend

Keep:

- API/session/request handling in `app/api/` and `app/main.py`.
- Business workflows in `app/services/`.
- Database models/utilities in `app/db/`.
- Migrations in `alembic/`.
- Schemas in `app/schemas/`.

### Frontend

Keep:

- Presentation logic in `app/templates/` and `app/static/`.

Preserve:

- Desktop layout integrity.
- Mobile responsiveness.
- Touch-friendly interactions.
- Consistent spacing and hierarchy.
- Existing interaction patterns.

Avoid:

- Unnecessary animations.
- Layout instability.
- Client-side business rules when server state should decide.

## Critical Invariants

These areas are high-risk and require extra caution:

- Reservation state transitions.
- Inventory state transitions.
- Check-in/check-out flows.
- Branch/user visibility rules.
- Auth/session boundaries.
- OTA parsing and matching logic.
- Pricing calculations.
- Cross-module utilities.
- Execution-critical functions.

Do not modify these blindly. Always inspect before changing behavior:

- Execution flows.
- Affected callers.
- Downstream dependencies.
- Related services.
- Permissions/session scope.

Never expose secrets in code. Keep secrets in environment variables. Never bypass permission checks for convenience.

# Engineering Rules

## Decision Rules

Before implementing:

- State assumptions explicitly when uncertainty exists.
- If multiple interpretations exist, ask or present options.
- Prefer the simplest working solution.
- Push against unnecessary complexity.
- Do not silently introduce architectural changes.
- If scope is unclear, stop and clarify first.

## Simplicity Rules

- Prefer the smallest working solution.
- Avoid speculative abstractions.
- Avoid abstractions for single-use logic.
- Reuse existing patterns before introducing new architecture.
- Avoid unnecessary dependencies.
- Avoid premature optimization.
- Prefer readability over cleverness.
- If a solution feels overly generic, simplify it.
- Do not create reusable abstractions until duplication or repetition is proven.

## Surgical Change Rules

- Touch only files directly related to the task.
- Do not refactor unrelated code.
- Do not rewrite stable working code unnecessarily.
- Preserve existing naming and structure.
- Match existing project style and patterns.
- Remove only artifacts introduced by your own changes.
- Keep change directly tied to the requested task.

If unrelated issues are discovered:

- Mention them separately.
- Do not silently fix them.

## Scope Discipline

Do not expand scope without explicit approval.

If additional improvements are discovered:

- Mention them separately.
- Do not implement automatically.

Avoid:

- Opportunistic rewrites.
- Cleanup-only edits.
- Unrelated refactors during feature work.

## Stability Rules

- Prefer stable working code over idealized refactors.
- Minimize regression risk over code elegance.
- Avoid broad rewrites unless explicitly requested.
- Preserve existing execution flow stability.
- Prefer consistency over architectural perfection.

## Architecture Safety

- Do not silently introduce new architecture patterns.
- Do not move logic between layers unless requested.
- Preserve existing service boundaries.
- Preserve existing request/session ownership.
- Respect existing module responsibilities.

## Verification Workflow

### Bug Fixes

Verify:

- Reproduction before fix when possible.
- Fix behavior.
- Regression risk.

### Refactors

Verify:

- Before behavior.
- After behavior.
- Unchanged external behavior.

### UI Changes

Verify:

- Desktop layout integrity.
- Mobile responsiveness.
- Touch interactions.
- Modal behavior.
- No broken states.
- No layout shifts.

### API / Backend Changes

Verify:

- Response compatibility.
- Affected consumers.
- Permissions/session scope.
- Filters/query behavior.
- Data consistency.

### Before Commit

Always:

- Inspect git diff/status.
- Run relevant tests.
- Verify changed flows.
- Run `gitnexus_detect_changes()`.

Never claim behavior was tested if it was not. Clearly distinguish:

- Verified behavior.
- Assumptions.
- Unverified expectations.

## Task Completion Workflow

Before considering a task complete:

1. Verify implementation.
2. Verify no regressions.
3. Inspect git diff for unrelated changes.
4. Verify affected execution flows.
5. Update documentation if behavior changed.
6. Summarize affected modules and risks.

## Documentation Sync

When changes affect:

- Architecture.
- Execution flows.
- Business rules.
- API contracts.
- Database structure.
- UI interaction patterns.
- Operational workflows.

Update corresponding `.claude/` or `docs/` files.

Documentation updates should:

- Describe final behavior only.
- Avoid implementation history.
- Preserve existing formatting.
- Remain concise and navigable.
- Update only affected sections.

Avoid:

- Changelog-style updates.
- Rewriting entire documents unnecessarily.

## Response Behavior

- Be concise and direct.
- Surface uncertainty early.
- Explain tradeoffs clearly.
- Prefer concrete reasoning over generic advice.
- Do not pretend certainty when uncertain.
- Avoid unnecessary verbosity.

## Anti-Patterns

Never:

- Rewrite large files unnecessarily.
- Introduce frameworks without request.
- Silently change architecture.
- Mix feature work with unrelated refactors.
- Mass rename with raw find/replace.
- Create speculative abstractions.
- Add layers for hypothetical future use.
- Bypass verification workflows.
- Modify unrelated formatting/styles.

# GitNexus — Code Intelligence

This repository is indexed by GitNexus as `binbinops`.

Use GitNexus MCP tools to:

- Understand architecture.
- Inspect execution flows.
- Analyze blast radius.
- Trace runtime behavior.
- Safely refactor symbols.

If any GitNexus tool reports a stale index, run:

```bash
npx gitnexus analyze
```

## GitNexus Workflow

Use GitNexus before modifying:

- Shared business logic.
- Auth/session flows.
- Reservation/inventory state transitions.
- OTA parsing/matching logic.
- Pricing calculations.
- Cross-module utilities.
- Execution-critical functions.

## Explore Unfamiliar Systems

Use:

```js
gitnexus_query({query: "concept"})
```

To:

- Discover related execution flows.
- Inspect connected processes.
- Avoid broad grepping.

## Understand Symbol Relationships

Use:

```js
gitnexus_context({name: "symbolName"})
```

To inspect:

- Callers.
- Callees.
- Dependencies.
- Execution flows.

## Analyze Blast Radius

Before modifications use:

```js
gitnexus_impact({
  target: "symbolName",
  direction: "upstream"
})
```

Review:

- Callers.
- Affected processes.
- Downstream impact.
- Risk level.

If risk level is `HIGH` or `CRITICAL`, explain risks before continuing.

## Safe Refactoring

Never mass rename symbols using raw find/replace.

Use:

```js
gitnexus_rename()
```

for symbol renames.

## Before Commit

Always run:

```js
gitnexus_detect_changes()
```

Verify:

- Affected symbols.
- Execution flows.
- Expected blast radius.
- Unrelated modifications.

## GitNexus Resources

| Resource | Purpose |
| --- | --- |
| `gitnexus://repo/binbinops/context` | Repository overview and index freshness |
| `gitnexus://repo/binbinops/clusters` | Functional architecture areas |
| `gitnexus://repo/binbinops/processes` | Execution flow inventory |
| `gitnexus://repo/binbinops/process/{name}` | Detailed process trace |

## GitNexus Skills

| Goal | Skill |
| --- | --- |
| Architecture exploration | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Impact analysis | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Debugging flows | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Refactoring and renaming | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tool references | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| CLI workflows | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

# Common Workflows

## Build / Start

See: `.claude/commands/build.md`.

## Testing

See: `.claude/commands/test.md`.

## Deploy

See: `.claude/commands/deploy.md`.

## Architecture

See: `docs/architecture.md`.

## Business Rules

See: `docs/business/`.

## API Notes

See: `docs/api/`.

## Runbooks

See: `docs/runbooks/`.

## Technical Decisions

See: `docs/decisions/`.

## Recent Operational Fixes

### 1. WMS Active Ticket Date Filter Bypass (May 2026)
- **Problem**: Active pending or shipping tickets (`PENDING`, `SHIPPING`) from previous months were hidden by default because the front-end WMS page lists filter by the current month range. However, they were still counted by global sidebar notification badges, causing a permanent badge count vs list view mismatch and preventing users from ever resolving (receiving/completing) old tickets.
- **Fix**: Skip date range queries on `requests.py` list APIs (`get_request_tickets` & `get_request_tickets_list`), `page_load.py` count APIs (`get_page_load` & `get_reception_page_load`), and `overview.py` SQL stats query when explicitly checking unresolved active statuses (`PENDING`, `SHIPPING`). Active tickets now correctly remain visible in the dashboard and lists regardless of creation date, aligning counts perfectly.

### 2. Relocated & Synced Pending Approvals Badge (May 2026)
- **Problem**: The pending approvals count badge was nested inside the inner tab "Chờ duyệt" (Pending) segment button, making it hard to notice from other main WMS tabs.
- **Fix**: 
  - Removed old segment badges from all variations of `tab_approvals.html` templates.
  - Placed a pulsing, animated count badge directly on the main header navigation tab **"Duyệt yêu cầu"** (Approve requests) inside both `manager/index.html` and `reception_request.html`.
  - Synced the count between independent Alpine.js scopes (header vs main body content) by dispatching a custom window event `inventory:set-pending-count` inside the app's `initApp()` method and `$watch` handlers in `static/js/inventory/manager/index.js` and `modules/reception_request/index.js`.

# Local Claude Runtime

Load only files relevant to the current task. Avoid loading unrelated architecture notes, patterns, tasks, or rule modules.

## Runtime Structure

```text
.claude/
├── agents/        # role briefs for backend/frontend/QA work
├── commands/      # build/test/deploy command docs
├── rules/         # durable behavioral rules
├── skills/        # reusable local workflows
├── tasks/         # persistent task briefs
├── patterns/      # repeated implementation patterns
├── architecture/  # Claude-facing architecture maps
└── worktrees/     # isolated worktrees
```

## Rule Files

- `.claude/rules/coding.md`
- `.claude/rules/architecture.md`
- `.claude/rules/naming.md`
- `.claude/rules/uiux.md`
- `.claude/rules/verification.md`
- `.claude/rules/gitnexus.md`

Use `.claude/architecture/` for compact Claude navigation notes. Keep durable product and technical documentation in `docs/`.

Use `.claude/patterns/` only after repetition is proven.

Use `.claude/tasks/` only for task state that must survive chat context. Do not use `.claude/tasks/` as an issue tracker replacement.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **binbinops** (13577 symbols, 19389 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/binbinops/context` | Codebase overview, check index freshness |
| `gitnexus://repo/binbinops/clusters` | All functional areas |
| `gitnexus://repo/binbinops/processes` | All execution flows |
| `gitnexus://repo/binbinops/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
