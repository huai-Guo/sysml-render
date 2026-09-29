# SysON Phase 0 — result log

## Current status

**Automated black-box path: PASS against SysON v2026.9.0.**

The live integration ran in GitHub Actions with the real `eclipsesyson/syson:v2026.9.0` container and PostgreSQL 15.

The preparation environment itself did not have Docker, so browser/manual graphical checks remain separate. We do not claim those as completed.

## Automated checks completed

- [x] SysON v2026.9.0 container starts successfully.
- [x] REST health check works.
- [x] Project creation works through `POST /api/rest/projects`.
- [x] Textual `.sysml` fixture imports successfully.
- [x] Explorer GraphQL subscription exposes the uploaded document resource ID.
- [x] REST semantic inventory contains all required golden elements/types.
- [x] Textual SysML export succeeds for the imported document.
- [x] Programmatic semantic insertion through `InsertTextualSysMLv2` succeeds.
- [x] The semantic mutation is observable through the SysML v2 REST API.
- [x] The mutated model exports back to textual SysML.
- [x] A General View can be created programmatically through GraphQL.
- [x] The created diagram can be rediscovered through `editingContext.representations`.
- [x] The returned representation kind is a Sirius diagram.
- [x] Python syntax/helper tests pass.

## Latest successful evidence

Successful automated flow:

```text
[1/10] SysON health
   PASS
[2/10] create project
   PASS
[3/10] import vehicle.sysml
   PASS
[4/10] inspect semantic inventory
   PASS — 59 elements
[5/10] export textual SysML
   PASS
[6/10] InsertTextualSysMLv2 mutation
   PASS
[7/10] REST verification after mutation
   PASS
[8/10] export mutated textual SysML
   PASS
[9/10] create General View programmatically
   PASS
[10/10] rediscover representation through GraphQL
   PASS
```

The successful run produced:

- a real SysON project ID;
- a real document ID discovered from Explorer;
- a semantic element ID for `VehicleArchitecture`;
- a real General View representation ID;
- textual exports before and after semantic mutation.

The CI uploads the evidence bundle as the `phase0-results` artifact.

## Important finding 1 — upload operation ID is not document ID

The first live run exposed an integration trap.

`UploadDocumentSuccessPayload.id` is the mutation/operation ID, not the uploaded document resource ID.

The Sirius Web Java payload internally contains a `DocumentDTO`, but the GraphQL schema for `UploadDocumentSuccessPayload` exposes only:

```text
id
report
```

Therefore `sysml-render` must not treat the upload payload ID as a document ID.

The robust public path proven by this spike is:

```text
uploadDocument
      |
      v
Explorer GraphQL subscription
      |
      v
TreeItem(kind = siriusWeb://document)
      |
      v
document resource id
```

That resource ID is accepted by the textual document download/export endpoint.

## Important finding 2 — a General View is programmatically creatable

The spike queries:

```text
editingContext.representationDescriptions(objectId)
```

for the target semantic element, selects the General View description, then calls:

```text
createRepresentation
```

with:

- editing context ID;
- semantic object ID;
- representation description ID;
- representation name.

SysON's representation input processor creates/attaches the corresponding `ViewUsage` automatically for standard diagrams.

The resulting representation ID can then be rediscovered from:

```text
editingContext.representations
```

This is a strong positive signal for an Agent-facing `render_model` API because no browser automation is required just to create and identify a diagram.

## Important finding 3 — image export has an existing Sirius Web path

Sirius Web provides a separate Diagram Image Server designed for programmatic export of existing diagrams as SVG or PNG.

Its conceptual endpoints are:

```text
/api/svg-diagram/{editingContextId}/{diagramId}
/api/png-diagram/{editingContextId}/{diagramId}
```

This has not yet been integrated into this repository's Phase-0 compose stack, but it is now the preferred candidate for the visual-output side of future `render_model`.

That gives the intended Agent pipeline a concrete shape:

```text
SysML text/file
     |
     v
SysON semantic model
     |
     v
create/discover General View
     |
     +--> diagramId + semantic metadata
     |
     v
Diagram Image Server
     |
     +--> SVG / PNG
     |
     v
MCP render_model result
```

## Manual graphical checks still pending

These checks require viewing/interacting with the actual web editor:

- [ ] nested General View/package visual quality accepted;
- [ ] recursive exposure behavior accepted;
- [ ] drill-down UX accepted;
- [ ] Interconnection-style view behavior accepted;
- [ ] drag/resize behavior accepted;
- [ ] layout persistence after browser/server restart accepted;
- [ ] UI semantic edit -> textual export round-trip manually inspected.

The checklist remains in `docs/spikes/SYSON_PHASE0.md`.

## Current Phase-0 assessment

### Strong positive evidence

SysON already gives us, through public/external surfaces:

- SysML textual import;
- SysML semantic access;
- textual export;
- programmatic semantic mutation;
- programmatic General View creation;
- stable representation discovery inside the persisted project;
- a Sirius Web ecosystem path for PNG/SVG export.

### Remaining architectural questions

Before freezing SysON as the production engine we still need to prove:

1. how we programmatically control which semantic elements are exposed in a General View;
2. whether nested package rendering is acceptable for our "large box contains smaller box" UX;
3. how much diagram layout state is available/controllable through GraphQL;
4. whether the Diagram Image Server works cleanly with the SysON deployment;
5. whether we embed SysON UI, extend it, or build our own shell around the backend;
6. how stable the relevant GraphQL surfaces are across SysON/Sirius Web upgrades.

## Interim decision

**Continue with the SysON-adapter path. Do not switch to GLSP yet.**

Phase 0 has passed the hardest backend/integration gates that would have forced an immediate fallback:

- model import is programmatic;
- semantic access is programmatic;
- semantic mutation is programmatic;
- export is programmatic;
- diagram creation/discovery is programmatic.

The next spike should focus on **view content + rendering + layout**, not on replacing the semantic engine.
