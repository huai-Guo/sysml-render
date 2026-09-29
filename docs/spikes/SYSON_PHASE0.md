# SysON Phase 0 — executable spike

## Goal

Decide whether SysON can be the first semantic/graphical engine behind `sysml-render` without coupling our product directly to SysON internals.

The spike treats SysON as a black box and uses only:

- SysML v2 REST API (`/api/rest`);
- Sirius Web GraphQL (`/api/graphql`);
- GraphQL file upload (`/api/graphql/upload`);
- the normal SysON browser UI for diagram-specific behavior.

This is deliberate. If Phase 0 only works by importing Java implementation classes from SysON, the adapter boundary has already failed.

## Why v2026.9.0

The spike defaults to the stable `v2026.9.0` container line. SysON documents `YEAR.MONTH.0` releases as the stable releases and its local test deployment is Docker Compose + PostgreSQL.

Override the image without editing the compose file:

```powershell
./scripts/start_syson.ps1 -ImageTag eclipsesyson/syson:v2026.9.0
```

## Automated path

```text
vehicle.sysml
    |
    v
POST /api/rest/projects
    |
    v
GraphQL currentEditingContext
    |
    v
uploadDocument(.sysml)
    |
    +---------------------------+
    |                           |
    v                           v
REST element inventory      textual export
    |                           |
    v                           v
expected semantic IDs/types  sentinel check
    |
    v
insertTextualSysMLv2
(TelemetryModule + telemetry)
    |
    v
REST verify mutation
    |
    v
textual export after mutation
```

Run on Windows PowerShell:

```powershell
./scripts/start_syson.ps1
python scripts/syson_phase0.py run-all
```

Generated evidence goes to `.phase0-results/`:

```text
.phase0-results/
  elements-before.json
  elements-after.json
  export-before.sysml
  export-after.sysml
  phase0-summary.json
```

The script fails hard if:

- SysON is unreachable;
- project creation fails;
- the fixture cannot be imported;
- expected semantic elements/types are missing;
- textual export loses required sentinels;
- the programmatic semantic insertion is not observable via REST;
- post-mutation export does not contain the inserted elements.

## Golden model intent

`examples/phase0/vehicle.sysml` intentionally covers the minimum useful cross-section:

```text
SysmlRenderPhase0 package
|
+-- PowerPort : PortDefinition
+-- Battery : PartDefinition
|   +-- capacity : AttributeUsage
|   +-- powerOut : PortUsage
|
+-- Controller : PartDefinition
|   +-- powerIn : PortUsage
|
+-- ElectricalSystem : PartDefinition
|   +-- battery : PartUsage
|   +-- controller : PartUsage
|   +-- connection between ports
|
+-- Vehicle : PartDefinition
|   +-- electrical : PartUsage
|
+-- MaintainabilityRequirement : RequirementDefinition
|
+-- VehicleArchitecture : Package
    +-- vehicle : PartUsage
    +-- Requirements : nested Package
        +-- maintainability : RequirementUsage
```

This gives us package nesting, definition/usage identity, ports, relationships and requirements without pulling in domain libraries or unit libraries that would make import dependencies obscure the editor test.

## Manual diagram checklist

The following checks are intentionally manual in Phase 0 because they validate the actual graphical editor behavior, not merely the semantic HTTP API.

### A. General View

1. Open the project created by `phase0-summary.json`.
2. Select `SysmlRenderPhase0` or `VehicleArchitecture`.
3. Create a **General View**.
4. Expose package/part content.
5. Verify that `VehicleArchitecture` can act as a visual container.
6. Verify that nested `Requirements` can be exposed inside/under that scope.
7. Record whether recursive exposure gives a useful "large box contains smaller box" experience.

Pass if the semantic hierarchy is understandable without flattening everything onto one level.

### B. Drill-down

1. Open a view rooted at `VehicleArchitecture`.
2. Open/navigate to `Vehicle` / `ElectricalSystem` detail.
3. Confirm that switching scope is usable without requiring one infinitely nested diagram.

Pass if a high-level overview and a detailed subsystem view can coexist.

### C. Interconnection View

1. Create/switch to an **Interconnection View** for the structural scope that contains `battery` and `controller`.
2. Verify both parts and their ports are representable.
3. Verify the connection between `powerOut` and `powerIn` is visible or can be exposed.

Pass if structural connectivity can be expressed without custom renderer code.

### D. Layout-only edit

1. Move `battery` and `controller` nodes.
2. Resize at least one valid container/node.
3. Refresh the browser.
4. Stop SysON without deleting the volume, start it again, reopen the view.
5. Verify positions/sizes persist.
6. Run `python scripts/syson_phase0.py run-all` on a fresh project and compare semantics: layout manipulation must not require modifying the `.sysml` meaning.

Pass if graphical state persists independently of textual model meaning.

### E. Semantic edit through UI

1. Rename a disposable semantic element in the UI.
2. Export the document through SysON.
3. Verify the exported textual SysML contains the semantic change.

Pass if UI semantic editing round-trips into textual SysML.

### F. Stable programmatic identity

From `.phase0-results/elements-before.json`, record the `@id` of:

- `VehicleArchitecture`;
- `Vehicle`;
- `ElectricalSystem`;
- `battery`;
- `controller`.

After browser refresh and server restart, query the same project again and record the IDs. Do **not** assume that export/re-import into a new project preserves IDs; this check is only about identity stability inside one persisted project.

## Decision table

| Capability | Required | Evidence | Status |
|---|---:|---|---|
| import `.sysml` | yes | automated probe | pending runtime |
| export textual SysML | yes | automated probe | pending runtime |
| REST semantic inventory | yes | automated probe | pending runtime |
| programmatic semantic mutation | yes | `insertTextualSysMLv2` | pending runtime |
| nested General View | yes | manual UI | pending runtime |
| Interconnection View | yes | manual UI | pending runtime |
| layout persistence | yes | manual restart test | pending runtime |
| semantic edit round-trip | yes | UI edit + export | pending runtime |
| no browser automation required for model API | yes | automated probe | designed yes |
| direct access to render/view metadata suitable for MCP | yes | GraphQL investigation | pending |

## Decision rule

Choose **SysON adapter** for Phase 1 only if all hard requirements above pass or have a small, explicitly bounded workaround.

Switch the engine investigation to **GLSP + separate SysML semantic engine** if any of these are true:

- programmatic model mutation requires UI/browser automation;
- diagram/view state cannot be programmatically identified well enough for Agent integration;
- imported/exported semantic content loses required model concepts;
- embedding/customizing the UI requires pervasive forks of SysON/Sirius Web;
- model element identity cannot be managed predictably inside a project;
- a stable image/diagram representation cannot be obtained for the future `render_model` tool.

## Known Phase-0 boundary

The local execution environment used while preparing the spike does not contain Docker, so the live container could not be started there. GitHub Actions is configured to run the same black-box probe against an actual SysON v2026.9.0 container. Python syntax/unit checks are also run independently.
