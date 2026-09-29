# Phase 0 — SysON Technical Spike

Status: executable spike

This spike determines whether Eclipse SysON can be used as the first semantic and representation engine behind sysml-render.

The goal is not to prove that SysON can display a diagram. The goal is to prove that we can drive a real SysML model, view, and edit loop through stable programmatic boundaries.

## Baseline

Target reference: SysON v2026.9.x documentation/API behavior.

Relevant upstream facts used by this spike:

- SysON exposes GraphQL at /api/graphql.
- textual SysML files can be uploaded through the Sirius Web GraphQL upload endpoint.
- SysON supports textual SysML import/export as an interchange mechanism.
- the SysML v2 standard REST API is only partially implemented in SysON.
- Sirius Web GraphQL is currently documented as experimental, therefore our application must isolate it behind an adapter.
- a local single-user SysON can be started using the official Docker Compose distribution.

These facts are exactly why sysml-render owns a ModelEngine abstraction instead of spreading GraphQL queries through the UI.

## Fixture

Primary fixture:

    examples/nested-system/vehicle-model.sysml

Expected semantic hierarchy:

    VehicleModel
    ├─ Interfaces
    │  ├─ PowerPort
    │  └─ ControlPort
    ├─ Requirements
    │  ├─ PowerContinuityRequirement
    │  └─ MotorControlRequirement
    ├─ Definitions
    │  ├─ Battery
    │  │  └─ powerOut
    │  ├─ Controller
    │  │  ├─ powerIn
    │  │  └─ motorCommand
    │  ├─ Motor
    │  │  ├─ powerIn
    │  │  └─ commandIn
    │  ├─ ElectricalSystem
    │  │  ├─ battery
    │  │  ├─ controller
    │  │  ├─ motor
    │  │  ├─ batteryPower
    │  │  └─ motorControl
    │  └─ Vehicle
    │     └─ electrical
    └─ Usages
       ├─ vehicle
       ├─ powerContinuity
       └─ motorControl

This is intentionally small enough to inspect manually while still exercising the concepts needed by our renderer.

# 1. Environment

Use the current official SysON local-test Docker Compose package.

Expected application endpoint:

    http://localhost:8080

The official local-test route requires Docker. A source installation has additional Java, Node, and PostgreSQL requirements; we do not need a source build for this spike.

Create a blank SysON project in the UI and copy its project UUID.

On Windows PowerShell install the smoke-test dependency:

    py -m pip install -r scripts/requirements.txt

Run the API-driven import:

    py scripts/syson_smoke.py examples/nested-system/vehicle-model.sysml --project-id <PROJECT_UUID>

Expected terminal result:

    PASS: SysML document imported through SysON API
    {
      "projectId": "...",
      "editingContextId": "...",
      "documentId": "..."
    }

Record the returned IDs. These IDs become inputs to later API tests.

# 2. Import tests

## T0.1 File upload

Action: execute scripts/syson_smoke.py.

Pass criteria:

- HTTP and GraphQL succeed.
- SysON reports UploadDocumentSuccessPayload.
- a document ID is returned.
- imported elements are visible in Explorer.

Fail criteria:

- parser rejects the fixture.
- import completes with unresolved core relationships.
- only a static artifact is created.

Evidence:

    Project ID:
    Editing context ID:
    Document ID:
    SysON version:
    Import report:
    Result: PASS / FAIL

## T0.2 Textual insertion

This is intentionally separate from document upload.

Test SysON's insertTextualSysMLv2 mutation against an existing Namespace with a tiny semantic addition such as:

    part def BackupBattery;

Pass:

- a semantic element is added below the chosen Namespace.
- it appears in Explorer.
- it can later be exposed in a diagram.

Why this matters: the future MCP operation apply_sysml_text_patch needs a semantic path that does not require browser automation.

# 3. General View tests

Create a General View rooted at a namespace containing the fixture.

## T0.3 Package projection

Expose Definitions, Interfaces, Requirements, and Usages.

Check:

- they render as semantic graphical elements, not screenshots.
- selection maps to concrete semantic objects.
- deleting a representation can be distinguished from deleting the model element.

## T0.4 Recursive package exposure

Exercise recursive exposure on Definitions.

Expected visual idea:

    ┌──────────────────── Definitions ────────────────────┐
    │                                                     │
    │  ┌──────── Battery ────────┐                        │
    │  │ powerOut                │                        │
    │  └─────────────────────────┘                        │
    │                                                     │
    │  ┌────── Controller ───────┐   ┌──── Motor ──────┐  │
    │  │ powerIn                 │   │ powerIn          │  │
    │  │ motorCommand            │   │ commandIn        │  │
    │  └─────────────────────────┘   └──────────────────┘  │
    │                                                     │
    │  ┌──────────── ElectricalSystem ─────────────────┐   │
    │  │ battery   controller   motor                  │   │
    │  └───────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────┘

The exact visual shape is not the pass condition.

Pass:

- nested semantic ownership can be represented.
- the user can navigate from parent to child context.
- we can retrieve which semantic ID each graphical node represents.

# 4. Interconnection View test

## T0.5 Structural projection

Open an Interconnection View around ElectricalSystem.

Expected semantic content:

    battery        controller        motor
       │               │               │
    powerOut ─────── powerIn            │
                       │                │
                  motorCommand ─── commandIn

Pass:

- part usages are represented.
- ports can be represented.
- connection usages resolve to the intended endpoints.
- moving a graphical node does not alter connection semantics.

A package-only tree renderer is not enough for engineering models; this test is a blocker.

# 5. Layout edit test

## T0.6 Move and resize

Actions:

1. drag controller.
2. resize one container.
3. reload the page.
4. restart SysON if needed.
5. reopen the representation.

Pass:

- layout persists.
- semantic model text does not gain meaningless x/y coordinates.
- the connection still resolves to the same semantic endpoints.

Record:

    Before layout:
    After layout:
    Exported SysML semantic difference:
    Representation persistence after reload: yes/no
    Result: PASS / FAIL

# 6. Semantic edit tests

## T0.7 Rename

Rename controller to mainController.

Pass:

- Explorer updates.
- all representations of that semantic object update.
- textual export reflects the semantic rename.
- connection semantics remain valid.

## T0.8 Create/delete element

Create a second battery usage beneath ElectricalSystem.

Pass:

- this is a real SysML semantic element.
- textual export contains it.
- deleting it removes or invalidates all corresponding representations.

## T0.9 Relationship edit

Create one valid relationship graphically, then remove it.

Pass:

- textual export changes semantically.
- re-import preserves the result.

# 7. Export / round-trip test

Download the imported document through the SysON document HTTP endpoint.

The current SysON API cookbook documents the route as:

    GET /api/editingcontexts/{editingContextId}/documents/{documentId}

Run this round trip:

    fixture
      -> SysON import
      -> semantic edit
      -> textual export
      -> new blank project
      -> re-import

Compare:

- package membership.
- definitions and usages.
- ports.
- relationship endpoints.
- requirement elements.

Pass: the semantic model needed by our MVP survives the round trip. Source formatting does not need to be byte-for-byte identical.

# 8. Programmatic representation test

This is a blocker for using SysON as our first engine.

Use GraphQL introspection during the spike rather than hard-coding guesses.

First query:

    {
      __schema {
        types {
          name
        }
      }
    }

Then identify current schema paths for:

- project.
- current editing context.
- representations.
- representation descriptions.
- diagrams.
- semantic target IDs.
- execution of editing tools.

We need to prove:

    projectId
      -> editingContextId
      -> representation/view
      -> graphical node
      -> semantic target ID

and at least one mutation in the reverse direction:

    programmatic command
      -> SysON edit operation
      -> semantic change
      -> affected representation updates

Pass: no browser DOM scraping or Playwright clicking is required for core integration.

# 9. Adapter decision record

| Capability | Required | Result | Evidence |
|---|---:|---|---|
| textual file import | yes | pending | |
| textual insertion | yes | pending | |
| nested package visualization | yes | pending | |
| General View | yes | pending | |
| Interconnection View | yes | pending | |
| semantic ID from representation | yes | pending | |
| persistent layout editing | yes | pending | |
| semantic rename | yes | pending | |
| create/delete semantic element | yes | pending | |
| relationship edit | yes | pending | |
| textual export | yes | pending | |
| semantic round trip | yes | pending | |
| API-driven model access | yes | pending | |
| API-driven semantic edit | yes | pending | |
| render/representation extraction | yes | pending | |

Decision rule:

Choose SysON adapter when all blocker rows pass: semantic import/export, nested/structural views, semantic IDs, API-driven semantic editing, and persistent representations.

Choose GLSP plus a separate SysML engine investigation if one of those core boundaries fundamentally requires SysON UI/browser automation or prevents us from owning a stable integration protocol.

Do not reject SysON merely because its UI does not match our final UX. Phase 0 asks whether SysON can act as a semantic/editor engine behind our own product boundary.

# 10. Agent-specific acceptance test

The final Phase 0 test simulates the future MCP workflow without implementing MCP yet.

Required result shape:

    {
      "modelId": "...",
      "revision": "...",
      "viewId": "...",
      "rootElementId": "...",
      "semanticElementIds": ["..."],
      "diagnostics": []
    }

Required operations:

1. import SysML via API.
2. discover the semantic element representing ElectricalSystem.
3. discover or create a representation.
4. identify graphical representations to semantic IDs.
5. perform one layout edit.
6. perform one semantic rename.
7. export textual SysML.
8. re-import and validate.

If all eight can be implemented without browser automation, SysON has passed the architectural portion of Phase 0.
