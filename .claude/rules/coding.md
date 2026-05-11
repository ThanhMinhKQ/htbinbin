# Coding Rules

- Prefer small vertical changes over broad rewrites.
- Keep route handlers thin; move business rules into services.
- Keep SQLAlchemy persistence concerns in `app/db/` or dedicated service helpers.
- Validate external input at API boundaries with Pydantic or explicit checks.
- Do not hide database or integration failures unless product flow requires graceful degradation.
- Avoid comments unless they explain non-obvious constraints.
- Preserve Vietnamese domain labels and UI copy unless task asks for copy changes.
