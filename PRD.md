# Product Requirements Document — sysml-render

## 1. Product

**sysml-render**

A standalone visualization and interactive graphical editing environment for SysML v2 models.

This repository is intentionally separate from `sysml-agent`.

The core separation is:

```text
sysml-agent
  = understand / generate / modify / validate / repair SysML

sysml-render
  = visualize / navigate / manually edit SysML models
```

Canonical model:

```text
*.sysml
```

The graphical representation is a view of the SysML model, not the source of truth.

---

## 2. Product Vision

A user should be able to open a SysML v2 model and understand or edit it visually without being forced into a static SVG workflow.

The editor should eventually support the interaction expected from a serious modeling environment:

- drag and move nodes;
- resize containers;
- create/delete model elements;
- create/reconnect relationships;
- edit properties and labels;
- nested diagrams and containers;
- multiple views of the same semantic model;
- navigation between elements/views;
- links from one view to another;
- synchronization between graphical edits and SysML;
- integration with `sysml-agent` for AI-assisted modeling.

The product is not merely a prettier renderer.

It is intended to become a graphical SysML workbench.

---

## 3. Why This Is a Separate Project

Visualization introduces a different class of complexity from AI generation.

`sysml-agent` should stay focused on producing correct SysML.

`sysml-render` owns:

- layout;
- graphical interaction;
- diagram state;
- editor UX;
- model-to-view mapping;
- direct manipulation;
- navigation;
- future collaborative editing.

This separation allows both projects to evolve independently.

---

## 4. Product Relationship

```text
                    *.sysml
                  /    |    \
                 /     |     \
                v      v      v
              Git   sysml-agent   sysml-render
                      |               |
                      |               |
                      +----- MCP -----+
                              |
                              v
                    AI-assisted editing
```

Neither project should require the other in order to run.

### sysml-agent without sysml-render

Valid use cases:

- CLI generation;
- validation;
- repair;
- automated pipelines;
- repository-based workflows.

### sysml-render without sysml-agent

Valid use cases:

- open an existing SysML file;
- inspect a model;
- move/edit model elements;
- manually update model structure.

### Combined

The editor can optionally ask the agent to:

- explain an element;
- repair selected SysML;
- generate a subsystem;
- add a requirement;
- modify a selected part of the model;
- validate the current model;
- propose a patch.

---

## 5. Core User Jobs

### Job A — Visualize a SysML model

Input:

```text
model.sysml
```

Expected:

- parse/load the model;
- create one or more graphical views;
- render model structure clearly;
- preserve semantic identity of elements.

### Job B — Navigate a complex model

Users should be able to:

- open an element;
- drill into nested structures;
- jump between related elements;
- navigate between views;
- return to previous context.

### Job C — Directly edit the model

Users should eventually be able to:

- add/remove elements;
- drag elements;
- change relationships;
- edit names/properties;
- create nested structures;
- reconnect edges.

Edits must update the semantic SysML representation, not only screen coordinates.

### Job D — Use AI from the editor

Example:

1. user selects `Battery`;
2. user requests "add a redundant backup battery";
3. editor provides current model/selection to `sysml-agent`;
4. agent returns a SysML patch/change;
5. editor previews the change;
6. user accepts/rejects;
7. resulting model is revalidated.

---

## 6. Functional Requirements

### FR-1 SysML as canonical source

The product SHALL treat SysML/model semantics as canonical.

A diagram SHALL NOT become an independent model that can silently diverge from SysML.

### FR-2 Graphical visualization

The editor SHOULD support:

- nodes;
- relationships;
- ports;
- compartments;
- containers;
- nested model elements;
- multiple diagram/view types.

### FR-3 Direct manipulation

The editor SHOULD support:

- move;
- resize;
- add;
- delete;
- connect;
- reconnect;
- direct label/property editing.

### FR-4 Model synchronization

A semantic edit should update affected views.

A valid graphical semantic edit should produce the corresponding SysML/model change.

Layout-only changes should not alter model semantics.

### FR-5 Multiple views

A single semantic element MAY appear in more than one view.

The product must distinguish:

```text
semantic model state
vs
diagram/view state
```

### FR-6 Nested navigation

Users SHOULD be able to:

- enter nested systems/subsystems;
- navigate parent/child views;
- jump to referenced elements;
- follow model relationships.

### FR-7 Linking

Future views SHOULD support links between:

- elements;
- diagrams;
- subviews;
- requirements and satisfying elements;
- structural and behavioral representations.

### FR-8 Validation integration

The editor SHOULD be able to call a SysML validator and surface diagnostics near affected elements/text.

The validator implementation should not be hardcoded into the graphical layer.

### FR-9 MCP / agent integration

The product SHOULD expose or consume a stable integration protocol.

MCP is a preferred candidate.

Potential operations:

```text
get_current_model
get_selected_element
get_current_view
validate_model
apply_sysml_patch
preview_sysml_patch
explain_element
generate_subsystem
repair_selection
```

The exact protocol is deferred.

### FR-10 Export / preview

The product MAY provide export formats such as:

- SVG;
- PNG;
- PDF;
- static shareable views.

Static export is secondary to interactive editing.

---

## 7. Technology Directions

No framework decision is frozen yet.

### Candidate A — Eclipse SysON / Sirius Web

Why evaluate first:

- SysML v2 native focus;
- web-based modeling environment;
- existing graphical editing capabilities;
- semantic model/view concepts already exist;
- potentially much less SysML-specific editor work.

Questions to answer in a spike:

- can it consume/update our canonical SysML workflow cleanly?
- can it be embedded or extended without taking over the whole product?
- can selected model context be exposed cleanly to MCP/agent integrations?
- how difficult is deployment?
- how tightly does it couple us to its own semantic/model repository?

### Candidate B — Eclipse GLSP

Why evaluate:

- purpose-built framework for graphical editors;
- supports nodes, edges, ports, compartments and nested structures;
- supports edit operations rather than only rendering;
- gives stronger control over custom UX and agent integration.

Cost:

- GLSP is not itself a SysML implementation;
- SysML semantic mapping/edit semantics would be our responsibility;
- more implementation work.

### Candidate C — custom web graph stack

Only evaluate if SysON and GLSP both create unacceptable constraints.

Avoid building a custom graph editor prematurely.

---

## 8. MVP — Deferred

Implementation is intentionally **not started yet**.

When this project becomes active, the first spike should answer a single question:

> Which technology gives us a true SysML graphical editor with acceptable integration complexity?

Suggested spike comparison:

```text
SysON
vs
GLSP
```

Evaluate using one small but representative SysML model.

The spike should test:

1. open/load model;
2. display nested structure;
3. drag a node;
4. add a relationship;
5. edit a semantic property;
6. persist the change;
7. re-open and verify;
8. obtain selected-element context programmatically;
9. apply a programmatic model change;
10. assess MCP integration feasibility.

No production editor should be built before this comparison.

---

## 9. Non-Functional Requirements

### NFR-1 Semantic correctness

Visual convenience must never corrupt model semantics silently.

### NFR-2 Separation from sysml-agent

The editor must not import agent internals.

Integration uses stable model/protocol boundaries.

### NFR-3 Web-first preference

A browser-based/editor-embeddable architecture is preferred unless evidence strongly favors another approach.

### NFR-4 Extensibility

The product should allow future:

- plugins;
- custom views;
- model-specific styling;
- AI operations;
- collaboration;
- external tool integrations.

### NFR-5 Large-model usability

Future design should account for:

- large graphs;
- lazy loading;
- view scoping;
- incremental updates;
- responsive pan/zoom/navigation.

---

## 10. Product Boundaries

`sysml-render` is not responsible for:

- choosing LLM providers;
- RAG;
- autonomous SysML generation;
- agent orchestration;
- owning the canonical validator;
- replacing `sysml-agent`.

It is the graphical consumption/editing layer for SysML.

---

## 11. Initial Roadmap

Development is deferred while `sysml-agent` is the primary project.

When resumed:

1. SysON vs GLSP technical spike;
2. freeze editor architecture;
3. read-only visualization prototype;
4. direct semantic editing;
5. nested/multi-view navigation;
6. validator diagnostics integration;
7. MCP/agent integration;
8. richer editing/export/plugin capabilities.

Until then, this PRD is the only intended artifact in this repository.
