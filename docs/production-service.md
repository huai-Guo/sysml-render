# Production semantic image service

The existing SysON editor is a local/internal workbench, not a multi-user public API. The production agent uses a separate stateless service in `src/sysml_render`: the pinned Pilot parser supplies authored entities and semantic relationships; this service returns an escaped SVG with the same source SHA-256. It neither imports user data into shared SysON projects nor persists layout/files.

Acceptance: reject unauthenticated or oversized requests, duplicate IDs and missing internal references; preserve only supplied semantic relationships; escape XML labels; bound projection work; expose omitted external/unnamed elements as coverage diagnostics. Tests exercise these boundaries. A diagram is a structural semantic overview, not proof of engineering correctness or full diagram coverage for every SysML construct.

Install `uv sync`, set `SYSML_RENDER_SERVICE_TOKEN` to a random secret of at least 32 characters and run `uv run uvicorn sysml_render.api:app --host 0.0.0.0 --port 8081`. Deploy only on the private component network behind sysml-agent. No public port is needed. `/health/live` is public; `/v1/render` requires the service bearer token. User tokens must never be forwarded here. The agent owns user authorization and artifacts.

The maximum request is 4 MiB, 5,000 input entities, 10,000 input relations, 250 displayed nodes and 1,500 displayed edges. Select a subtree with `root_id` for larger models. Over-limit graphs fail explicitly; they are not silently truncated. Omitted external/unnamed references are counted in `coverage`.
