# Architecture Rules

- Use GitNexus impact analysis before editing any function, class, or method.
- Read relevant docs in `docs/` before changing PMS, OTA, booking, pricing, CRM, loyalty, or inventory flows.
- Keep HTTP/session concerns in API layer; keep domain transitions in services.
- Do not introduce global state for cross-request behavior.
- Do not add executable hooks unless user explicitly asks.
- For UI changes, verify rendered page or state inability to verify.
