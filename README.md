# sysml-render

Web-first SysML v2 automatic renderer and editable diagram workbench.

Core principle: a renderer should not force users to manually reconstruct relationships that already exist in the SysML semantic model.

## Current pipeline

    SysML text / .sysml
            |
            v
         SysON
      semantic engine
            |
            v
    Normalized Semantic Model
            |
            v
      Projection Engine
            |
            +-- node discovery
            +-- typed feature projection
            +-- semantic relationship materialization
            +-- projection profiles
            |
            v
        Diagram IR
            |
            v
       Layout Engine
            |
            v
      Interactive View
            |
            +-- drag nodes
            +-- inspect semantic IDs
            +-- persist layout-only state

SysON is currently used as a semantic backend. sysml-render owns automatic diagram synthesis; it does not expose SysON's manual element-exposure workflow as the rendering UX.

## Current capabilities

- paste SysML v2 text or upload a .sysml file;
- automatically create or reuse a SysON project;
- read semantic data through SysON's SysML v2 REST API;
- normalize backend data behind a renderer-owned contract;
- automatically select a root and projection profile;
- automatically discover visible nodes;
- automatically materialize existing semantic relationships as edges;
- project typed ports/features into usage context;
- automatically calculate an initial layout;
- recursively lay out Package/definition/usage containers as nested boxes;
- render a draggable interactive HTML view;
- persist manual layout separately from SysML;
- expose the same renderer through Web, CLI, HTTP and MCP;
- run projection, layout, adapter, Web and MCP tests in CI.

## Semantic safety rule

The renderer may visualize a relationship that already exists in SysML.

It must never invent a SysML relationship just to make the diagram look connected.

For example, this existing semantic connection may automatically become a visual edge:

    connection batteryPower connect
        battery.powerOut to controller.powerIn;

But two parts with no semantic relationship remain semantically unconnected.

## Install

Python 3.12 is recommended. A running SysON instance is currently required.

    py -m pip install -r requirements.txt

Default SysON endpoint:

    http://localhost:8080

Optional environment variables on PowerShell:

    $env:SYSON_URL = "http://localhost:8080"
    $env:SYSON_TOKEN = "<token-if-needed>"
    $env:SYSML_RENDER_STATE_DIR = ".sysml-render-state"

## Web application

Run:

    py -m uvicorn apps.web.app:app --reload --host 127.0.0.1 --port 3000

Open:

    http://127.0.0.1:3000

The left side accepts pasted SysML or an uploaded .sysml file. The right side renders the automatically synthesized diagram.

Dragging a node persists presentation state through the layout API. Coordinates are stored in renderer-owned .sysmlview.json-style state, not in the SysML semantic source.

## One-step CLI

Import and render a file:

    py scripts/render_sysml.py ^
      --file examples/nested-system/vehicle-model.sysml ^
      --select ElectricalSystem ^
      --output out/electrical-system.html

PowerShell can use backtick line continuation instead of ^.

The command creates/reuses a project, imports SysML, reads the semantic model, selects a view root, synthesizes nodes and semantic edges, lays out the graph, and writes an interactive HTML view.

Render an existing SysON project:

    py scripts/render_syson_html.py ^
      --project-id <PROJECT_ID> ^
      --select ElectricalSystem ^
      --output out/electrical-system.html

Selection accepts an element ID, exact name, or qualified name. A single root package can be selected automatically.

## MCP server

The implementation uses the current MCP Python SDK v2 server API.

Run locally over stdio:

    py apps/mcp/server.py

Or inspect it with:

    mcp dev apps/mcp/server.py

Current tools:

- render_sysml: import textual SysML and automatically synthesize an editable view;
- render_project: render an existing SysON project;
- get_view: read a specific renderer view including persisted layout edits;
- apply_layout_command: move/pin a visual node without changing SysML semantics;
- get_semantic_element: retrieve one semantic element for Agent reasoning.

Human Web edits and Agent MCP layout edits share the same renderer-owned view state.

render_sysml returns structured Diagram IR, layout data, semantic identifiers, diagnostics, and a self-contained interactive HTML preview.

For Streamable HTTP:

    $env:MCP_TRANSPORT = "streamable-http"
    $env:MCP_HOST = "127.0.0.1"
    $env:MCP_PORT = "8000"
    py apps/mcp/server.py

## Architecture

Semantic adapter:

    adapters/syson/rest_adapter.py

Automatic projection:

    prototype/projection.py

Stable diagram boundary:

    prototype/graph_ir.py
    schemas/diagram-ir.schema.json

Layout:

    prototype/layout.py

Presentation-only persistent state:

    prototype/view_state.py

Web UI:

    apps/web/app.py

MCP:

    apps/mcp/server.py

## Tests

Run:

    py -m unittest discover -s tests -v

Important invariants include:

- no semantic relationship means no invented visual edge;
- typed projected ports retain semantic identity plus usage context;
- projected edges receive routes;
- manually moved parts keep projected ports with them;
- persisted view state does not become semantic model state;
- SysON REST payloads normalize into the same renderer contract;
- Web text/file input returns an automatically synthesized graph;
- MCP exposes the same renderer core.

## Remaining major work

1. validate against a live current SysON deployment in addition to mocked upstream API shapes;
2. support arbitrary feature chaining, inheritance and redefinition;
3. normalize richer connection, flow and interface semantics;
4. replace the simple layout with a production nested-graph layout engine;
5. add resize, collapse, hide/show and richer view-state editing;
6. add semantic graphical edits such as rename/create/delete/reconnect;
7. deepen requirement and behavior projection profiles;
8. add image/vector export while preserving the editable view as the primary artifact;
9. add MCP semantic-edit tools with revision/precondition handling.

See PLAN.md and docs/spikes/phase-0-syson.md for the full roadmap.


## Experimental semantic editing in Web

The Web editor now separates importing from refreshing:

- Import/paste textual SysML through `POST /api/render`.
- Refresh an existing semantic project through `POST /api/projects/{projectId}/render`; this **does not reimport** previously submitted source.
- Click a node in the rendered canvas to inspect/select its semantic identity.
- When explicitly enabled, rename it, create an owned element or delete an unreferenced leaf definition.
- After a semantic command succeeds, the Web UI rereads the semantic model and reconstructs the view.

**Semantic writes are disabled by default** because the SysON commit writer has contract/mock tests but has not been validated against a real running SysON v2026.9 instance here. The view stays readable/draggable without enabling model writes.

To enable experimental editing **only against a disposable test SysON project**, before launching Web:

    $env:SYSON_ENABLE_SEMANTIC_WRITES = "1"

Other safeguards:

- derived/typed-port projection nodes cannot be edited as independent semantic objects via the UI;
- create is restricted to known definition/package element kinds and compatible owners;
- delete requires typing the exact selected name and API-level confirmation;
- delete refuses elements with children, type references, or directly reported semantic relationship references;
- layout changes still only affect `.sysmlview.json` state.

These are MVP guards, not a complete referential-integrity validator. In particular, unreported derived or implicit SysML references may still exist. **Do not enable semantic writes for important models before a live integration review.**

### Run the live SysON semantic smoke

The following script **always creates a fresh project** and never accepts an existing project ID. It validates import, rename, owned-element creation, semantic reread/parent reconstruction, and delete.

    py scripts/syson_semantic_smoke.py --url http://localhost:8080 --allow-writes

The script prints the new project ID and intentionally leaves the test project available for inspection or manual cleanup. It can modify/delete test elements *inside that new project* only.

Unlike the default CI tests, this requires a real running SysON server. CI success by itself must not be taken as proof that real SysON writes or graphical round-tripping work.


## Automatic semantic connection editing (Web and MCP)

The structure view can now turn **two existing visible PortUsage nodes**
into a SysML `ConnectionUsage`. This is an explicit semantic edit, not a
layout-only line.

With `SYSON_ENABLE_SEMANTIC_WRITES=1` set **only for a disposable SysON
project**:

1. Import or open the project's **Structure** view rooted at its PartDefinition.
2. Click the first port, then **设为源 Port**.
3. Click the second port, then **设为目标 Port**.
4. Enter a safe connection name (simple SysML identifier).
5. Click **创建语义连接**.

For example, choosing `battery.powerOut` and `motor.powerIn` under
`ElectricalSystem` generates:

```sysml
connection batteryToMotor connect battery.powerOut to motor.powerIn;
```

The UI validates both ports against the current semantic feature chains,
rejects duplicate diagram edges and duplicate relationship names, then uses
the SysON `insertTextualSysMLv2` GraphQL mutation on the existing
semantic parent. Unlike `uploadDocument`, this inserts text in the
chosen owner instead of importing another document.

A post-write check distinguishes:

- `acknowledged`: SysON GraphQL reported `SuccessPayload`;
- `observedInModel`: semantic REST reread found the newly named ConnectionUsage;
- `edgeVisible`: a new projected edge links the selected visual endpoints;
- `verified`: both semantic observation and edge visualization succeeded.

If GraphQL acknowledges a write but verification fails, **inspect the
model rather than clicking Create again**. The project may have been
modified, while the semantic adapter could not yet map the connection
endpoints back to a view.

The same operation is exposed to MCP Agents through `create_connection`:

```text
create_connection(
    project_id,
    root_semantic_id,
    source_node_id,
    target_node_id,
    name
)
```

All semantic writer tools, whether Web or MCP, are disabled by default
until `SYSON_ENABLE_SEMANTIC_WRITES=1` is set. Position/layout commands
remain separate.

### Live SysON connection smoke

The following command **always creates a new disposable project** from
`examples/nested-system/vehicle-model.sysml` and attempts a new
`battery.powerOut -> motor.powerIn` connection.

```powershell
py scripts/syson_connection_smoke.py `
  --url http://localhost:8080 `
  --allow-writes
```

It checks: textual import → normalized semantic elements and typed
ports → connection command → GraphQL insertion → REST reread →
automatically projected edge. The test project is left in SysON so it
can be inspected and manually removed.

**This live smoke is not run in GitHub Actions.** CI uses isolated
contract fixtures and mock HTTP responses; it does not prove that the
exact installed SysON server supports every mutation or that all
relationship endpoint references normalize correctly.

### Conservative deletion audit

Deletion now shares a fail-closed reference audit between Web and MCP.
It checks normalized child ownership, typing, relationship references,
and also queries SysON's direct `GET elements/{id}/relationships`
endpoint. If that query fails or returns relationships that have not
been safely classified for cascade deletion, the operation is refused.

This deliberately favors preserving model integrity over permitting
deletions. It does not yet constitute a complete SysML v2 reference
dependency engine: inherited, implied, and backend-specific references
still need a live metamodel-level audit.
