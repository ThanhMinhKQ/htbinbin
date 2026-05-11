# GitNexus Rules

- Repo name: `binbinops`.
- For unfamiliar feature work, start with `gitnexus_query` instead of broad grep.
- Before editing any function, class, or method, run `gitnexus_impact` upstream on target symbol.
- If impact risk is HIGH or CRITICAL, warn user before edits.
- For API route handler edits, run route impact/shape checks when route is indexed.
- Before commit, run `gitnexus_detect_changes()` and compare affected flows with intended scope.
- For renames, use `gitnexus_rename`; do not find-and-replace symbols.
