# sysml-render

Web-first SysML v2 visualization and graphical editing research project.

## Current stage: SysON Phase-0 spike

The project is intentionally testing the semantic/editor engine before building a custom canvas.

### Windows quick start

Requirements:

- Docker Desktop;
- Python 3.11+;
- `requests` (`pip install requests`).

Run:

```powershell
./scripts/start_syson.ps1
python scripts/syson_phase0.py run-all
```

Then open `http://localhost:8080` and execute the graphical checklist in:

```text
docs/spikes/SYSON_PHASE0.md
```

Stop while preserving PostgreSQL data:

```powershell
./scripts/stop_syson.ps1
```

Delete the Phase-0 database as well:

```powershell
./scripts/stop_syson.ps1 -DeleteData
```

## Repository direction

- `PLAN.md` — architecture and staged product plan;
- `examples/phase0/` — SysML golden fixture + semantic expectations;
- `scripts/syson_phase0.py` — black-box REST/GraphQL integration probe;
- `infra/syson/` — reproducible local SysON environment;
- `docs/spikes/` — spike procedure, evidence and decision criteria.

The canonical semantic model remains textual SysML. Diagram/view state is treated separately.
