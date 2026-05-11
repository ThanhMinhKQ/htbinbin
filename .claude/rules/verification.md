# Verification Rules

- Match verification to risk: targeted test for logic, browser check for UI, migration dry review for schema.
- Before claiming UI work done, run the app and inspect affected browser flow when possible.
- Before committing, inspect `git status`, inspect diff, and run `gitnexus_detect_changes()`.
- If a required check cannot run, state exact reason and remaining risk.
- Do not use `--no-verify` or skip hooks unless user explicitly asks.
- Do not mark task complete when tests or checks fail unresolved.
