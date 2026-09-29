# Automatic Projection Prototype

This directory contains the first executable core of sysml-render.

The prototype intentionally separates three concerns:

1. semantic model input;
2. diagram synthesis;
3. layout/rendering.

It does not depend on SysON UI behavior.

## Pipeline

    normalized semantic snapshot
        -> ProjectionEngine
        -> DiagramIR
        -> LayoutEngine
        -> interactive HTML preview

The semantic snapshot is currently a fixture. A future SysON adapter will produce the same normalized input from the live SysML model.

## Run the structure projection

    python scripts/project_semantic_graph.py       examples/nested-system/vehicle-semantic.json       --root partdef:ElectricalSystem       --profile structure

The result contains:

- ElectricalSystem as the diagram root;
- battery, controller, and motor PartUsage nodes;
- context-specific port projections;
- batteryPower and motorControl edges derived from existing semantic ConnectionUsage objects.

No edge is invented by the renderer.

## Generate an interactive preview

    python scripts/render_projection_html.py       examples/nested-system/vehicle-semantic.json       --root partdef:ElectricalSystem       --profile structure       --output out/electrical-system.html

Open out/electrical-system.html in a browser.

The preview demonstrates:

- automatic node discovery;
- automatic semantic relationship materialization;
- automatic initial layout;
- nested port rendering;
- semantic IDs attached to visual elements;
- dragging part nodes while their projected ports and edges follow.

It is deliberately dependency-free and is not the final web editor.

## Why typed ports are projected

For this SysML structure:

    part battery : Battery;

and a Battery definition that owns:

    port powerOut : PowerPort;

the visible endpoint in an ElectricalSystem view is conceptually:

    battery.powerOut

The renderer therefore creates a context-specific visual node whose:

- semantic identity points to Battery::powerOut;
- context identity points to the battery PartUsage.

This distinction becomes important for feature chaining, inherited features, multiple instances of the same definition, and relationship endpoints.

## Current limitations

The prototype intentionally does not yet solve:

- arbitrary-depth feature chaining;
- inherited/redefined features;
- interface/flow semantics;
- requirement relationship projection;
- behavioral views;
- full nested package layout;
- ELK integration;
- persisted manual layout overrides.

Those are subsequent conformance cases, not reasons to mix projection logic back into the parser or UI.
