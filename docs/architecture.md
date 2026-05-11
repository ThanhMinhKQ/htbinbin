# Architecture

## System shape

FastAPI application for Bin Bin hotel operations: internal HR/task workflows, PMS, OTA ingestion, booking, inventory, pricing, CRM, and reservation flows.

## Main layers

- `app/main.py`: FastAPI app setup, middleware, routers, startup jobs, static/upload mounts.
- `app/api/`: HTTP route modules and PMS routers.
- `app/services/`: business workflows and integrations.
- `app/db/`: SQLAlchemy models, sessions, database utilities.
- `app/schemas/`: Pydantic request/response models.
- `app/templates/`: Jinja templates for server-rendered UI.
- `app/static/`: CSS and JavaScript for PMS, inventory, and shared UI.
- `alembic/`: database migrations.
- `tests/`: regression tests.

## Boundaries

- Routes validate HTTP input, manage request/session context, and delegate business work.
- Services own business rules and integration workflows.
- Database layer owns SQLAlchemy models, sessions, and persistence helpers.
- Templates/static assets own presentation only; avoid embedding business decisions in JS when server state should decide.

## Critical flows to map before editing

- Authentication/session branch selection.
- PMS check-in/check-out/stay/reservation/folio flows.
- OTA Gmail/PubSub ingestion and reservation matching.
- Inventory request creation and PMS integration.
- Pricing engine and booking engine flows.
- Guest CRM sync and loyalty flows.

## Navigation

- Use GitNexus first for unfamiliar flows: `gitnexus_query({query: "concept", repo: "binbinops"})`.
- Use `gitnexus_impact` before editing functions, classes, or methods.
- Read feature specs in `docs/` before changing matching modules.
