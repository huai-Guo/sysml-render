#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
if str(PROTOTYPE) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE))

from layout import SimpleHierarchicalLayout
from projection import ProjectionEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--root", required=True)
    parser.add_argument("--profile", default="structure")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def render_html(ir, layout) -> str:
    graph = ir.to_dict()
    layout_data = layout.to_dict()
    payload = json.dumps(
        {"graph": graph, "layout": layout_data},
        ensure_ascii=False,
    ).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sysml-render projection prototype</title>
<style>
  :root {{
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #172033;
    background: #f6f8fc;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; display: grid; grid-template-columns: 1fr 320px; height: 100vh; }}
  #viewport {{ overflow: auto; padding: 24px; }}
  #canvas {{
    position: relative;
    min-width: 900px;
    min-height: 520px;
    background:
      linear-gradient(#e9edf5 1px, transparent 1px),
      linear-gradient(90deg, #e9edf5 1px, transparent 1px),
      white;
    background-size: 24px 24px;
    border: 1px solid #dfe5ef;
    border-radius: 14px;
    box-shadow: 0 8px 30px rgba(31, 45, 75, .08);
  }}
  svg {{ position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible; }}
  .root {{
    position: absolute;
    border: 2px solid #72809b;
    border-radius: 16px;
    background: rgba(246, 248, 252, .72);
    pointer-events: none;
  }}
  .root-title {{
    position: absolute;
    top: 13px;
    left: 18px;
    font-weight: 700;
    font-size: 17px;
  }}
  .node {{
    position: absolute;
    border: 1px solid #a9b5c8;
    border-radius: 10px;
    background: white;
    box-shadow: 0 4px 12px rgba(31, 45, 75, .08);
    user-select: none;
  }}
  .part {{ cursor: grab; padding: 15px; }}
  .part:active {{ cursor: grabbing; }}
  .node-kind {{ color: #65738a; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }}
  .node-label {{ font-weight: 650; margin-top: 6px; }}
  .port {{
    position: absolute;
    border-radius: 50%;
    background: #fff;
    border: 3px solid #4d607f;
    z-index: 4;
    cursor: pointer;
  }}
  .port::after {{
    content: attr(data-label);
    position: absolute;
    white-space: nowrap;
    font-size: 11px;
    top: 15px;
    left: -3px;
    color: #4e5b70;
  }}
  .edge {{ fill: none; stroke: #566884; stroke-width: 2; }}
  aside {{
    border-left: 1px solid #dfe5ef;
    padding: 24px;
    background: #fbfcfe;
    overflow: auto;
  }}
  h1 {{ font-size: 19px; margin: 0 0 8px; }}
  .muted {{ color: #66748b; line-height: 1.5; font-size: 13px; }}
  pre {{ white-space: pre-wrap; word-break: break-word; font-size: 12px; background: white; border: 1px solid #e2e7f0; padding: 12px; border-radius: 10px; }}
</style>
</head>
<body>
<div id="viewport"><div id="canvas"></div></div>
<aside>
  <h1>Semantic inspector</h1>
  <p class="muted">Drag part nodes. Existing SysML connections are rendered automatically. Click a node or port to inspect semantic identity.</p>
  <pre id="selection">Nothing selected</pre>
</aside>
<script>
const data = {payload};
const canvas = document.getElementById("canvas");
const selection = document.getElementById("selection");
const graphNodes = new Map(data.graph.nodes.map(n => [n.id, n]));
const positions = new Map(data.layout.nodes.map(n => [n.id, {{...n}}]));
const edgeDefs = new Map(data.graph.edges.map(e => [e.id, e]));

canvas.style.width = data.layout.width + "px";
canvas.style.height = data.layout.height + "px";

const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
canvas.appendChild(svg);

function selectNode(node) {{
  selection.textContent = JSON.stringify(node, null, 2);
}}

function createNode(node) {{
  const p = positions.get(node.id);
  const el = document.createElement("div");
  el.dataset.id = node.id;

  if (node.id === data.graph.rootSemanticId) {{
    el.className = "root";
    el.innerHTML = '<div class="root-title">' + node.label + '</div>';
  }} else if (node.derived) {{
    el.className = "port";
    el.dataset.label = node.label;
  }} else {{
    el.className = "node part";
    el.innerHTML =
      '<div class="node-kind">' + node.kind + '</div>' +
      '<div class="node-label">' + node.label + '</div>';
  }}

  Object.assign(el.style, {{
    left: p.x + "px",
    top: p.y + "px",
    width: p.width + "px",
    height: p.height + "px"
  }});

  el.addEventListener("click", e => {{
    e.stopPropagation();
    selectNode(node);
  }});

  if (!node.derived && node.id !== data.graph.rootSemanticId) enableDrag(el, node);
  canvas.appendChild(el);
}}

function enableDrag(el, node) {{
  let start = null;
  el.addEventListener("pointerdown", e => {{
    el.setPointerCapture(e.pointerId);
    const p = positions.get(node.id);
    start = {{mouseX: e.clientX, mouseY: e.clientY, x: p.x, y: p.y}};
  }});
  el.addEventListener("pointermove", e => {{
    if (!start) return;
    const p = positions.get(node.id);
    const dx = e.clientX - start.mouseX;
    const dy = e.clientY - start.mouseY;
    const oldX = p.x, oldY = p.y;
    p.x = start.x + dx;
    p.y = start.y + dy;
    el.style.left = p.x + "px";
    el.style.top = p.y + "px";

    for (const child of data.graph.nodes.filter(n => n.parent_id === node.id && n.derived)) {{
      const cp = positions.get(child.id);
      cp.x += p.x - oldX;
      cp.y += p.y - oldY;
      const childEl = canvas.querySelector('[data-id="' + CSS.escape(child.id) + '"]');
      childEl.style.left = cp.x + "px";
      childEl.style.top = cp.y + "px";
    }}
    redrawEdges();
  }});
  el.addEventListener("pointerup", () => {
    if (start) {
      const p = positions.get(node.id);
      window.parent.postMessage({
        type: "sysml-render:layout-change",
        nodeId: node.id,
        x: p.x,
        y: p.y
      }, "*");
    }
    start = null;
  });
  el.addEventListener("pointercancel", () => start = null);
}}

function center(id) {{
  const p = positions.get(id);
  return {{x: p.x + p.width / 2, y: p.y + p.height / 2}};
}}

function redrawEdges() {{
  svg.replaceChildren();
  for (const edge of data.graph.edges) {{
    const s = center(edge.source);
    const t = center(edge.target);
    const mx = (s.x + t.x) / 2;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("class", "edge");
    path.setAttribute("d", "M " + s.x + " " + s.y + " H " + mx + " V " + t.y + " H " + t.x);
    svg.appendChild(path);
  }}
}}

const rootNode = graphNodes.get(data.graph.rootSemanticId);
createNode(rootNode);
for (const node of data.graph.nodes) {{
  if (node.id !== data.graph.rootSemanticId && !node.derived) createNode(node);
}}
for (const node of data.graph.nodes) {{
  if (node.derived) createNode(node);
}}
redrawEdges();
</script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    ir = ProjectionEngine(snapshot).project(args.root, args.profile)
    layout = SimpleHierarchicalLayout().layout(ir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(ir, layout), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
