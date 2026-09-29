# SysON Phase 0 — result log

## Current status

**Prepared; live integration is delegated to the branch CI.**

The local preparation environment does not provide a Docker executable, so no local live SysON result is claimed.

## Static checks completed

- [x] Python probe compiles.
- [x] Probe helper unit tests pass.
- [x] Golden fixture and expectation manifest are present.
- [x] Docker Compose follows the current SysON local-test topology: SysON app + PostgreSQL 15.
- [x] Probe uses documented REST/GraphQL surfaces rather than SysON Java internals.
- [x] GitHub Actions job added to start SysON v2026.9.0 and run the probe.
- [ ] Golden `.sysml` accepted by live SysON parser.
- [ ] Automated import/export checks pass against v2026.9.0.
- [ ] Programmatic textual semantic insertion passes.
- [ ] General View nested-container behavior accepted.
- [ ] Interconnection View accepted.
- [ ] Layout persistence accepted.
- [ ] Agent-facing view/representation metadata path proven.

## Runtime evidence

The CI job uploads `.phase0-results/` as the `phase0-results` artifact.

A passing automated probe must produce:

```text
elements-before.json
elements-after.json
export-before.sysml
export-after.sysml
phase0-summary.json
```

Do not mark Phase 0 complete from screenshots alone. The REST/GraphQL evidence and the manual diagram checks in `SYSON_PHASE0.md` are both required.
