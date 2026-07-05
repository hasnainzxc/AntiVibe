# Agent Instructions — Phase Gate Enforcement

## PHASE 2 GATE (CRITICAL)

Phase 2 (Strix Integration, tasks T10-T22 in `.omo/plans/antivibe-mvp-and-strix.md`) **MUST NOT** be started until ALL of the following conditions are met:

1. **Phase 1 tasks (T1-T9)** are marked complete in `.omo/plans/antivibe-mvp-and-strix.md`.
2. **At least 3 real repositories** have been scanned end-to-end successfully.
3. **The dashboard is publicly accessible** and displays the scan results correctly.
4. **Zero (0) unhandled errors** are observed in the production logs for 48+ consecutive hours.
5. **At least 1 real user feedback** has been collected and documented.

> [!WARNING]
> **If ANY condition is not fully met:** STOP. Fix Phase 1 issues. Do not modify or start any task in Phase 2.
