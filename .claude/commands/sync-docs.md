---
description: Audit docs-vs-code drift (Yatagarasu) and apply the fixes (Tenjin).
---

Reconcile the documentation with the current state of the code.

1. Launch the `yatagarasu` subagent (via the Agent tool) to audit documentation drift across `docs/` against the code it owns per `docs/00-doc-map.md`, including any changes in the current `git diff`. Ask it for a prioritized drift report.
2. Hand that report to the `tenjin` subagent (via the Agent tool) to apply the doc updates — the owning docs plus the "Aktueller Stand" bullet in `docs/04-roadmap.md`.
3. Summarize what drift was found and what changed. If Yatagarasu reports no drift, say so and stop.

$ARGUMENTS
