# sysml-render — Architecture & Implementation Plan

> Status: active technical spike  
> Goal: build a web-first SysML v2 renderer/editor that can be used directly by humans and programmatically by Agents.

## 1. What we are building

`sysml-render` is not a static diagram generator.

It should become a **semantic SysML v2 graphical workbench** with four first-class capabilities:

1. **Import**
   - paste SysML v2 textual syntax;
   - upload one or more `.sysml` files;
   - later: open projects through the SysML v2 API.

2. **Visualize**
   - show model structure as editable nodes/edges/compartments;
   - support nested containers;
   - support multiple views over the same semantic model;
   - allow drill-down from high-level package/system views to internal details.

3. **Edit**
   - move/resize nodes without changing SysML semantics;
   - rename/change properties/create/delete/connect model elements with semantic changes;
   - persist both semantic and graphical changes;
   - never let the graphical state silently diverge from the SysML model.

4. **Agent integration**
   - expose stable HTTP/API and MCP tools;
   - let an Agent render a model, inspect the current selection/view, obtain a preview image, and make controlled semantic or layout changes.

---

## 2. Important correction to the initial mental model

A useful default visualization is:

```text
package / system
┌──────────────────────────────────────────────┐
│ high-level elements                          │
│   ┌──────────────────┐  ┌────────────────┐   │
│   │ subsystem A      │  │ subsystem B    │   │
│   │  ┌────────────┐  │  │ ...            │   │
│   │  │ child      │  │  │                │   │
│   │  └────────────┘  │  │                │   │
│   └──────────────────┘  └────────────────┘   │
└──────────────────────────────────────────────┘
```

But the implementation **must not equate containment in the semantic model with containment in a diagram**.

We need two different concepts:

```text
Semantic model
  Package
    PartDefinition
    PartUsage
    RequirementUsage
    ...

Diagram / View
  which semantic elements are currently exposed
  node x/y/width/height
  collapsed/expanded
  visible/hidden
  edge routing
  selected diagram type
```

The same semantic element may appear in several views.

This is the core architectural rule for the entire project.

---

## 3. What SysON teaches us

Eclipse SysON is currently the strongest open-source reference implementation for the interaction model we want.

Relevant observations:

- SysON is a web-based SysML v2 editor built on Sirius Web.
- It supports graphical, textual and form-based editing.
- Its General View is associated with a Namespace-like semantic context rather than being a one-image-per-file renderer.
- Package elements can be represented inside a diagram and can recursively expose contained elements.
- Interconnection views focus on structural content such as parts, ports and connectors.
- diagrams are intentionally **views of semantic elements**, not the semantic source of truth.
- SysON supports importing complete `.sysml` files and inserting textual SysML content into an existing model.
- it supports textual export back to SysML.
- its web client uses GraphQL, while integration APIs include a subset of the SysML v2 REST API.
- diagram operations include direct edit, drag/drop, create/delete/connect and layout operations.

This matches our desired product semantics much better than an SVG/PlantUML pipeline.

### What we should *not* copy blindly

SysON is a substantial platform:

- Java/Spring backend;
- Sirius Web;
- PostgreSQL persistence;
- a large SysML-specific metamodel/service layer;
- its own representation infrastructure.

So our first task is not to fork the whole project.

Our first task is to prove which parts can be reused cleanly and where we need our own abstraction boundary.

---

## 4. Recommended product architecture

### 4.1 Logical architecture

```text
                     ┌──────────────────────────────┐
                     │          Human UI            │
                     │ editor / explorer / canvas   │
                     └──────────────┬───────────────┘
                                    │
                                    │ commands
                                    ▼
┌────────────────────────────────────────────────────────────────┐
│                    sysml-render application                    │
│                                                                │
│  ┌────────────────┐     ┌──────────────────┐                   │
│  │ Model Service  │     │   View Service   │                   │
│  │                │     │                  │                   │
│  │ semantic model │     │ exposed elements │                   │
│  │ IDs            │     │ layout           │                   │
│  │ relationships  │     │ routing          │                   │
│  │ validation     │     │ diagram type     │                   │
│  └───────┬────────┘     └────────┬─────────┘                   │
│          │                        │                             │
│          └──────────┬─────────────┘                             │
│                     ▼                                           │
│              ┌───────────────┐                                  │
│              │ Command layer │                                  │
│              │ semantic edit │                                  │
│              │ layout edit   │                                  │
│              └───────┬───────┘                                  │
└──────────────────────┼───────────────────────────────────────────┘
                       │
          ┌────────────┴──────────────┐
          ▼                           ▼
┌──────────────────┐         ┌────────────────────┐
│ SysML Engine     │         │ Integration Layer  │
│                  │         │                    │
│ initial: SysON   │         │ REST/GraphQL       │
│ future: pluggable│         │ MCP Server         │
└────────┬─────────┘         └─────────┬──────────┘
         │                             │
         ▼                             ▼
     *.sysml                     Agent / CLI / App
```

### 4.2 Mandatory abstraction

Create a backend interface conceptually similar to:

```ts
interface ModelEngine {
  importText(text: string): Promise<ModelHandle>;
  importFile(file: Uint8Array, name: string): Promise<ModelHandle>;

  getElement(id: string): Promise<ModelElement>;
  getChildren(id: string, recursive?: boolean): Promise<ModelElement[]>;
  getRelationships(scope: string): Promise<ModelRelationship[]>;

  applySemanticCommand(command: SemanticCommand): Promise<ChangeSet>;
  validate(modelId: string): Promise<Diagnostic[]>;

  exportSysML(modelId: string): Promise<string>;
}
```

The first adapter can target SysON.

If SysON later proves too heavy, we can replace that adapter without redesigning the web UI, MCP layer and view model.

### 4.3 Diagram Synthesis / Auto Projection Engine

A critical product responsibility is **automatic diagram synthesis**.

SysON's General View and Interconnection View are intentionally unsynchronized: importing a valid semantic model does not imply that every relevant element and relationship is automatically exposed in a useful diagram. That interaction model is acceptable for a generic modeling workbench, but it is not sufficient for `sysml-render`.

For our product, this belongs to the renderer:

```text
*.sysml
   │
   ▼
Semantic Model
   │
   ▼
Diagram Synthesis
   │
   ├─ choose root / scope
   ├─ select relevant semantic elements
   ├─ recursively include owned elements
   ├─ close over relevant relationships
   ├─ materialize ports / compartments
   ├─ choose visual-only containment cues
   ├─ choose diagram type
   └─ produce an initial graph
   │
   ▼
Auto Layout + Edge Routing
   │
   ▼
Editable View
```

The user should **not** have to manually add every existing element or redraw every relationship that already exists in the SysML model.

#### Semantic relationship rule

The renderer may automatically **materialize** a relationship that already exists semantically, but it must not invent a new SysML relationship merely to make the picture look connected.

Example:

```sysml
connection batteryPower connect
    battery.powerOut to controller.powerIn;
```

The first rendered view should automatically contain the corresponding visual edge when both endpoints are in scope.

By contrast, if two parts merely sit next to each other in a package and the model contains no connection/dependency/flow/etc., the renderer must not create a semantic relationship.

It may still use visual-only layout cues such as nesting, grouping, alignment, labels, or background containers.

#### Projection profiles

Automatic rendering should be profile-driven rather than "show every SysML element at once".

Initial profiles:

```text
package-overview
  -> packages + important definitions/usages + high-level relationships

structure
  -> parts + ports + connections/interfaces

requirements
  -> requirements + satisfy/derive/trace relationships

behavior
  -> actions/states + flows/successions
```

Each profile decides:

- root semantic element;
- traversal depth;
- included element kinds;
- included relationship kinds;
- whether containment becomes nesting or an explicit edge;
- whether referenced external elements are pulled into scope;
- compartment visibility;
- labeling rules;
- layout direction and grouping.

#### Relationship closure

For a selected node set `N`, derive visible edges from the semantic graph:

```text
E_visible =
  semantic relationships
  whose source and target are visible
  and whose relationship kind is enabled by the active projection profile
```

Optionally, a profile may expand one hop to include connected elements:

```text
seed nodes
   -> semantic neighbors
   -> include qualifying neighbor nodes
   -> include qualifying semantic edges
```

This is conceptually similar to SysON's "Add existing connected elements", but in `sysml-render` it is an automatic policy executed during initial rendering, not a repetitive manual user action.

#### Layout is also renderer responsibility

After projection, the renderer must generate a readable first layout automatically.

The pipeline is:

```text
semantic graph
  -> projection
  -> nested graph
  -> layout constraints
  -> node placement
  -> edge routing
  -> editable view state
```

Likely layout engine candidates include ELK for hierarchical/nested diagrams. The concrete engine can be replaced later.

Manual user moves then become overrides stored in the view state. Auto-layout should preserve pinned/manual elements when possible.

#### Updated boundary with SysON

SysON should therefore be evaluated primarily for:

- SysML parsing/metamodel;
- semantic identity;
- validation;
- semantic mutation;
- persistence;
- graphical editing primitives.

We should **not** depend on SysON's default manual exposure workflow as the rendering UX.

If SysON can be programmatically instructed to expose the graph synthesized by our projection engine, we can reuse its representation/editor runtime.

If not, we keep SysON only as a semantic engine and render the synthesized graph through our own graphical layer.

---

## 5. Data / file format strategy

This is one of the most important decisions.

### 5.1 Canonical semantic format

Keep:

```text
*.sysml
```

as the portable semantic source of truth.

Do **not** make SVG, PNG, draw.io, GraphML or a canvas JSON file the authoritative model.

### 5.2 Editable diagram state

There is no reason to force all graphical state into the `.sysml` text file.

Introduce an internal sidecar representation, initially:

```text
*.sysmlview.json
```

Example:

```json
{
  "schemaVersion": 1,
  "viewId": "view-123",
  "modelRevision": "rev-42",
  "kind": "general",
  "rootElementId": "element-package-1",
  "elements": {
    "element-a": {
      "visible": true,
      "x": 120,
      "y": 80,
      "width": 240,
      "height": 160,
      "collapsed": false,
      "pinned": true
    }
  },
  "edges": {
    "relationship-9": {
      "routing": "orthogonal",
      "bendPoints": []
    }
  }
}
```

Rules:

- semantic names/types/relationships do not live here;
- only presentation/view state lives here;
- all keys refer back to stable semantic element IDs;
- stale IDs are diagnosable, not silently recreated.

Later this can be replaced or mapped to a Sirius Web representation format if reuse proves safe.

### 5.3 Optional project bundle

For easy exchange we can later define:

```text
example.sysmlproj
  /model/*.sysml
  /views/*.sysmlview.json
  /manifest.json
```

This is our application package, not a replacement for the SysML standard.

### 5.4 Export formats

Support three different export intents:

| Intent | Format | Editable semantics? |
|---|---|---|
| Human preview | PNG | No |
| Vector documentation | SVG | No, only presentation |
| Continue editing | `.sysml` + view state / project bundle | Yes |

An SVG may include element IDs/metadata for click-through, but it still must not become the editor's source of truth.

---

## 6. Agent / MCP design

The Agent should not receive only an image.

A rendering tool should return **three channels at once**:

1. **visual preview**
   - PNG or SVG;
2. **structured machine-readable result**
   - model/view IDs, selected semantic elements, diagnostics;
3. **editable continuation**
   - a URL/session/view ID that the user or Agent can modify.

Conceptual MCP result:

```json
{
  "modelId": "m-123",
  "revision": "r-7",
  "viewId": "v-4",
  "rootElementId": "pkg-1",
  "viewKind": "general",
  "editableUrl": "http://localhost:3000/models/m-123/views/v-4",
  "diagnostics": [],
  "semanticElementIds": ["pkg-1", "part-2", "port-4"]
}
```

alongside an image content block.

### 6.1 Initial MCP tools

Keep the first surface deliberately small:

```text
import_sysml
render_model
get_view
get_element
get_selection
validate_model
apply_sysml_text_patch
apply_semantic_command
apply_layout_command
export_sysml
```

Later:

```text
create_view
set_view_root
expose_elements
hide_elements
arrange_view
create_relationship
reconnect_relationship
preview_changes
accept_changes
reject_changes
```

### 6.2 Separate semantic and layout commands

Examples:

```json
{
  "type": "renameElement",
  "elementId": "part-10",
  "newName": "BackupBattery"
}
```

is a semantic command.

```json
{
  "type": "moveNode",
  "viewId": "view-2",
  "elementId": "part-10",
  "x": 420,
  "y": 180
}
```

is a layout command.

Never mix the two command classes.

---

## 7. Human + Agent interaction model

Recommended workflow:

```text
Agent receives or generates SysML
           │
           ▼
     import_sysml
           │
           ▼
      semantic model
           │
           ▼
      render_model
      /          \
     /            \
preview image    editable view URL
     │            │
     │            ▼
     │       Human adjusts layout
     │       / model elements
     │            │
     └──────┬─────┘
            ▼
      semantic/view changes
            │
            ▼
        validation
            │
            ▼
       export *.sysml
```

The image is therefore a preview/communication artifact, not the editable representation itself.

---

## 8. Technology decision: first spike

We should perform a **SysON-first spike**, not a full implementation.

### Candidate A — SysON-backed renderer/editor

Use SysON as the initial semantic + representation engine.

Add our own thin integration layer for:

- text/file import;
- project/view creation;
- Agent-friendly view discovery;
- rendering/export;
- selected-element context;
- semantic commands;
- MCP.

**Why first:** almost every hard editor behavior we need already exists in some form.

**Risk:** platform weight and coupling.

### Candidate B — GLSP + custom SysML engine

Use GLSP for graphical editing and build our own semantic adapter.

**Why attractive:** cleaner product ownership and lighter custom UX.

**Cost:** we must implement or integrate:
- SysML parser/metamodel;
- semantic edit commands;
- validation;
- model-to-view projection;
- round-trip text serialization.

This should remain the fallback if SysON proves difficult to embed/automate.

### Candidate C — React graph library + custom implementation

Do not start here.

React Flow / Cytoscape / ELK can be useful implementation details later, but by themselves they do not solve SysML semantic editing.

---

## 9. Phase plan

## Phase 0 — Reference spike

Goal: answer whether SysON can serve as the first model/editor engine.

Use a representative sample with:

- nested packages;
- PartDefinition / PartUsage;
- attributes;
- ports;
- requirements;
- relationships;
- at least one nested subsystem.

Tests:

1. start SysON locally;
2. import `.sysml` file;
3. paste textual SysML into an existing context;
4. create a General View;
5. show nested Package contents recursively;
6. create an Interconnection View;
7. drag/resize a node;
8. move a semantic element to another valid container;
9. rename/edit an element;
10. create/delete a relationship;
11. export back to textual SysML;
12. restart/reopen and verify persistence;
13. programmatically discover the project/model/view through GraphQL/REST;
14. programmatically execute one semantic edit;
15. obtain enough representation data to build an Agent-facing result.

### Phase 0 pass criteria

SysON is accepted as the first engine if:

- imports our chosen sample with acceptable semantic fidelity;
- graphical edits persist;
- exported SysML preserves required model information;
- we can address semantic elements with stable IDs;
- a program can discover and mutate the model without browser automation;
- a program can identify a view and obtain useful rendering/context.

If these fail, move to the GLSP path.

---

## Phase 1 — Repository skeleton

Create:

```text
sysml-render/
  apps/
    web/
    mcp-server/
  packages/
    core/
    model-engine/
    view-model/
    protocol/
  adapters/
    syson/
  examples/
    nested-system/
  docs/
    architecture/
    spikes/
```

Responsibilities:

- `core`: commands, IDs, diagnostics, change sets;
- `model-engine`: interface only;
- `adapters/syson`: GraphQL/REST/SysON integration;
- `view-model`: presentation state abstraction;
- `protocol`: API/MCP schemas;
- `web`: product shell;
- `mcp-server`: Agent integration.

---

## Phase 2 — Read-only MVP

Deliver:

- paste SysML;
- upload `.sysml`;
- import/create model;
- tree explorer;
- General View rendering;
- nested Package visualization;
- zoom/pan/fit;
- click element -> details;
- drill down into a nested semantic element;
- PNG/SVG preview export;
- HTTP endpoint for rendering.

No semantic editing is required for this milestone.

Acceptance test:

```text
sysml text/file
   -> model
   -> rendered editable canvas representation
   -> element click maps back to semantic element ID
```

---

## Phase 3 — Layout editing

Deliver:

- drag;
- resize;
- collapse/expand;
- pin;
- hide/show;
- auto-layout;
- persist/reload view state.

This phase must prove that presentation changes do not mutate SysML semantics.

---

## Phase 4 — Semantic editing

Add in order:

1. rename;
2. simple property edit;
3. create/delete element;
4. move element to a semantic container;
5. create/delete relationship;
6. reconnect relationship.

Every command must:

```text
validate command
 -> apply semantic mutation
 -> validate model
 -> update affected views
 -> produce ChangeSet
 -> support undo/redo
```

---

## Phase 5 — MCP / Agent MVP

Expose:

- `import_sysml`;
- `render_model`;
- `get_element`;
- `get_view`;
- `validate_model`;
- `apply_semantic_command`;
- `apply_layout_command`;
- `export_sysml`.

`render_model` returns:

- visual preview;
- structured view metadata;
- editable URL;
- diagnostics.

Acceptance scenario:

```text
Agent:
"render this model"

-> tool imports/renders
-> Agent receives image + IDs + edit URL
-> human moves two nodes
-> Agent asks get_view
-> Agent sees updated layout
-> Agent renames a PartUsage
-> semantic model changes
-> export_sysml returns updated text
```

---

## Phase 6 — Multi-view and advanced SysML

Add:

- multiple General Views;
- Interconnection View;
- requirement-focused views;
- behavior views;
- view links;
- element shown in multiple views;
- cross-view navigation;
- large-model lazy loading.

---

## 10. Test strategy

The project should be test-first around round trips.

### Semantic invariant

```text
import SysML
 -> build/edit view only
 -> export SysML

semantic meaning must remain unchanged
```

### Semantic edit round trip

```text
import
 -> graphical semantic command
 -> export
 -> re-import
 -> compare semantic model
```

### Agent contract

MCP/API tests should verify:

- schemas remain stable;
- element IDs are valid;
- bad commands return diagnostics rather than corrupting state;
- stale revisions are rejected;
- render results always state model revision + view ID.

### Golden models

Maintain small fixtures:

```text
01-package-only.sysml
02-nested-packages.sysml
03-parts-ports.sysml
04-requirements.sysml
05-connections.sysml
06-multi-view.sysml
07-large-generated-model.sysml
```

Every engine adapter must pass the same conformance suite.

---

## 11. Key risks

### Risk A — SysON import/export is not perfectly lossless

Mitigation:
- choose golden fixtures;
- diff semantic models, not only source formatting;
- document unsupported concepts;
- keep original source/revision available during the spike.

### Risk B — SysON coupling becomes too deep

Mitigation:
- all calls go through `ModelEngine`;
- web/MCP code never imports SysON internals directly.

### Risk C — IDs are unstable across export/re-import

Mitigation:
- define model revision boundaries;
- support semantic lookup by qualified name/path where needed;
- treat cross-revision identity as a deliberate mapping problem.

### Risk D — diagram state and semantic state drift

Mitigation:
- view references semantic IDs only;
- semantic deletion invalidates/removes representations;
- every mutation returns affected view IDs.

### Risk E — Agent makes destructive edits

Mitigation:
- revision/precondition on commands;
- preview change set;
- undo/redo;
- optional approval before applying high-impact semantic changes.

---

## 12. Immediate next actions

The next implementation batch should be **Phase 0 only**:

1. add a representative nested SysML fixture;
2. add a spike document describing expected visual hierarchy;
3. run the fixture through a current stable SysON container;
4. record import/export gaps;
5. exercise SysON GraphQL/REST programmatically;
6. prove one programmatic semantic edit;
7. prove one persistent layout edit;
8. decide `SysON adapter` vs `GLSP implementation`.

Do not start a bespoke canvas renderer until this spike is complete.

---

## 13. Current recommendation

Use this architecture unless the spike disproves it:

```text
            *.sysml
               │
               ▼
        ModelEngine interface
               │
       ┌───────┴────────┐
       ▼                ▼
 SysON adapter       future engine
       │
       ▼
 semantic model / commands
       │
       ├──────────────► View model
       │                 │
       │                 ▼
       │              Web editor
       │
       └──────────────► API / MCP
                         │
                         ▼
                       Agent
```

The key product decision is therefore:

> **Do not send an Agent only a generated picture.**
>
> Return a picture for perception, structured semantic/view metadata for reasoning, and an editable view/session for continued interaction.

This preserves both human usability and Agent programmability while keeping SysML as the canonical semantic model.
