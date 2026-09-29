from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math

from graph_ir import DiagramIR, DiagramNode


@dataclass(frozen=True)
class NodeLayout:
    id: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class EdgeRoute:
    id: str
    points: list[tuple[float, float]]


@dataclass
class LayoutResult:
    width: float
    height: float
    nodes: list[NodeLayout] = field(default_factory=list)
    edges: list[EdgeRoute] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [
                {
                    "id": edge.id,
                    "points": [
                        {"x": point[0], "y": point[1]}
                        for point in edge.points
                    ],
                }
                for edge in self.edges
            ],
        }


class SimpleHierarchicalLayout:
    """Deterministic nested/container-aware Phase-0 layout.

    It deliberately keeps the ProjectionEngine independent of the layout
    implementation. A production ELK-backed implementation can later replace
    this class without changing DiagramIR.
    """

    ROOT_X = 40.0
    ROOT_Y = 40.0
    ROOT_HEADER = 52.0
    ROOT_PADDING = 60.0

    PART_WIDTH = 190.0
    PART_HEIGHT = 120.0
    PART_GAP = 90.0
    PORT_SIZE = 14.0

    CONTAINER_HEADER = 44.0
    CONTAINER_PADDING = 24.0
    CONTAINER_GAP = 24.0
    LEAF_WIDTH = 190.0
    LEAF_HEIGHT = 82.0
    MAX_CONTAINER_COLUMNS = 3

    def layout(
        self,
        ir: DiagramIR,
        overrides: dict[str, dict] | None = None,
    ) -> LayoutResult:
        if ir.profile == "package-overview":
            result = self._layout_nested_overview(ir)
        else:
            result = self._layout_structure(ir)

        layouts = {node.id: node for node in result.nodes}
        if overrides:
            self._apply_overrides(layouts, ir, overrides)

        routes = self._route_edges(ir, layouts)
        width, height = self._canvas_size(layouts)

        return LayoutResult(
            width=width,
            height=height,
            nodes=list(layouts.values()),
            edges=routes,
        )

    def _layout_structure(self, ir: DiagramIR) -> LayoutResult:
        node_by_id = {node.id: node for node in ir.nodes}
        root = node_by_id[ir.root_semantic_id]

        top_level = [
            node
            for node in ir.nodes
            if node.parent_id == root.id and not node.derived
        ]
        count = max(1, len(top_level))

        root_width = (
            self.ROOT_PADDING * 2
            + count * self.PART_WIDTH
            + max(0, count - 1) * self.PART_GAP
        )
        root_height = 300.0

        layouts: dict[str, NodeLayout] = {
            root.id: NodeLayout(
                id=root.id,
                x=self.ROOT_X,
                y=self.ROOT_Y,
                width=root_width,
                height=root_height,
            )
        }

        part_y = self.ROOT_Y + self.ROOT_HEADER + 45.0
        for index, node in enumerate(top_level):
            x = (
                self.ROOT_X
                + self.ROOT_PADDING
                + index * (self.PART_WIDTH + self.PART_GAP)
            )
            layouts[node.id] = NodeLayout(
                id=node.id,
                x=x,
                y=part_y,
                width=self.PART_WIDTH,
                height=self.PART_HEIGHT,
            )

        source_ids = {edge.source for edge in ir.edges}
        target_ids = {edge.target for edge in ir.edges}

        for parent in top_level:
            parent_layout = layouts[parent.id]
            children = [
                node
                for node in ir.nodes
                if node.parent_id == parent.id and node.derived
            ]

            left = [
                node
                for node in children
                if node.id in target_ids and node.id not in source_ids
            ]
            right = [node for node in children if node not in left]

            self._place_ports(layouts, parent_layout, left, side="left")
            self._place_ports(layouts, parent_layout, right, side="right")

        unplaced = [node for node in ir.nodes if node.id not in layouts]
        fallback_y = self.ROOT_Y + root_height + 40.0
        for index, node in enumerate(unplaced):
            layouts[node.id] = NodeLayout(
                id=node.id,
                x=self.ROOT_X + index * 180.0,
                y=fallback_y,
                width=150.0,
                height=70.0,
            )

        return LayoutResult(
            width=root_width + self.ROOT_X * 2,
            height=self.ROOT_Y + root_height + 60,
            nodes=list(layouts.values()),
            edges=[],
        )

    def _layout_nested_overview(self, ir: DiagramIR) -> LayoutResult:
        nodes = {node.id: node for node in ir.nodes}
        root = nodes[ir.root_semantic_id]

        children: dict[str, list[DiagramNode]] = {}
        for node in ir.nodes:
            if node.parent_id and not node.derived:
                children.setdefault(node.parent_id, []).append(node)

        sizes: dict[str, tuple[float, float]] = {}

        def measure(node: DiagramNode) -> tuple[float, float]:
            nested = children.get(node.id, [])
            if not nested:
                size = self._leaf_size(node)
                sizes[node.id] = size
                return size

            child_sizes = [measure(child) for child in nested]
            columns = min(
                self.MAX_CONTAINER_COLUMNS,
                max(1, math.ceil(math.sqrt(len(nested)))),
            )
            rows = math.ceil(len(nested) / columns)

            col_widths = [0.0] * columns
            row_heights = [0.0] * rows
            for index, (width, height) in enumerate(child_sizes):
                col = index % columns
                row = index // columns
                col_widths[col] = max(col_widths[col], width)
                row_heights[row] = max(row_heights[row], height)

            width = (
                self.CONTAINER_PADDING * 2
                + sum(col_widths)
                + self.CONTAINER_GAP * max(0, columns - 1)
            )
            height = (
                self.CONTAINER_HEADER
                + self.CONTAINER_PADDING * 2
                + sum(row_heights)
                + self.CONTAINER_GAP * max(0, rows - 1)
            )
            width = max(width, 260.0)
            height = max(height, 150.0)
            sizes[node.id] = (width, height)
            return width, height

        measure(root)

        layouts: dict[str, NodeLayout] = {}

        def place(node: DiagramNode, x: float, y: float) -> None:
            width, height = sizes[node.id]
            layouts[node.id] = NodeLayout(
                id=node.id,
                x=x,
                y=y,
                width=width,
                height=height,
            )

            nested = children.get(node.id, [])
            if not nested:
                return

            columns = min(
                self.MAX_CONTAINER_COLUMNS,
                max(1, math.ceil(math.sqrt(len(nested)))),
            )
            rows = math.ceil(len(nested) / columns)

            col_widths = [0.0] * columns
            row_heights = [0.0] * rows
            for index, child in enumerate(nested):
                child_width, child_height = sizes[child.id]
                col = index % columns
                row = index // columns
                col_widths[col] = max(col_widths[col], child_width)
                row_heights[row] = max(row_heights[row], child_height)

            col_x = []
            cursor_x = x + self.CONTAINER_PADDING
            for width_value in col_widths:
                col_x.append(cursor_x)
                cursor_x += width_value + self.CONTAINER_GAP

            row_y = []
            cursor_y = (
                y
                + self.CONTAINER_HEADER
                + self.CONTAINER_PADDING
            )
            for height_value in row_heights:
                row_y.append(cursor_y)
                cursor_y += height_value + self.CONTAINER_GAP

            for index, child in enumerate(nested):
                col = index % columns
                row = index // columns
                place(child, col_x[col], row_y[row])

        place(root, self.ROOT_X, self.ROOT_Y)

        # Derived nodes are uncommon in package overview, but keep the
        # invariant that every projected node receives a layout.
        unplaced = [
            node
            for node in ir.nodes
            if node.id not in layouts
        ]
        fallback_y = (
            self.ROOT_Y + sizes[root.id][1] + self.CONTAINER_GAP
        )
        for index, node in enumerate(unplaced):
            layouts[node.id] = NodeLayout(
                id=node.id,
                x=self.ROOT_X + index * 180.0,
                y=fallback_y,
                width=150.0,
                height=70.0,
            )

        return LayoutResult(
            width=sizes[root.id][0] + self.ROOT_X * 2,
            height=sizes[root.id][1] + self.ROOT_Y * 2,
            nodes=list(layouts.values()),
            edges=[],
        )

    def _leaf_size(self, node: DiagramNode) -> tuple[float, float]:
        if node.kind in {"Package", "LibraryPackage"}:
            return 220.0, 100.0
        if node.kind in {
            "PartDefinition",
            "RequirementDefinition",
            "PortDefinition",
        }:
            return self.LEAF_WIDTH, self.LEAF_HEIGHT
        return 170.0, 72.0

    def _route_edges(
        self,
        ir: DiagramIR,
        layouts: dict[str, NodeLayout],
    ) -> list[EdgeRoute]:
        routes: list[EdgeRoute] = []
        for edge in ir.edges:
            source = layouts.get(edge.source)
            target = layouts.get(edge.target)
            if source is None or target is None:
                continue

            sx = source.x + source.width / 2
            sy = source.y + source.height / 2
            tx = target.x + target.width / 2
            ty = target.y + target.height / 2
            middle_x = (sx + tx) / 2
            routes.append(
                EdgeRoute(
                    id=edge.id,
                    points=[
                        (sx, sy),
                        (middle_x, sy),
                        (middle_x, ty),
                        (tx, ty),
                    ],
                )
            )
        return routes

    def _canvas_size(
        self,
        layouts: dict[str, NodeLayout],
    ) -> tuple[float, float]:
        if not layouts:
            return 800.0, 500.0
        width = max(
            layout.x + layout.width
            for layout in layouts.values()
        ) + 40.0
        height = max(
            layout.y + layout.height
            for layout in layouts.values()
        ) + 40.0
        return width, height

    def _apply_overrides(
        self,
        layouts: dict[str, NodeLayout],
        ir: DiagramIR,
        overrides: dict[str, dict],
    ) -> None:
        by_parent: dict[str, list[str]] = {}
        for node in ir.nodes:
            if node.parent_id:
                by_parent.setdefault(node.parent_id, []).append(node.id)

        descendants_cache: dict[str, list[str]] = {}

        def descendants(node_id: str) -> list[str]:
            if node_id in descendants_cache:
                return descendants_cache[node_id]
            result: list[str] = []
            for child_id in by_parent.get(node_id, []):
                result.append(child_id)
                result.extend(descendants(child_id))
            descendants_cache[node_id] = result
            return result

        for node_id, override in overrides.items():
            if node_id not in layouts:
                continue
            x = override.get("x")
            y = override.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue

            old = layouts[node_id]
            dx = float(x) - old.x
            dy = float(y) - old.y
            layouts[node_id] = NodeLayout(
                id=old.id,
                x=float(x),
                y=float(y),
                width=old.width,
                height=old.height,
            )

            # Moving a visual container moves its complete visual subtree.
            for child_id in descendants(node_id):
                child = layouts.get(child_id)
                if child is None:
                    continue
                layouts[child_id] = NodeLayout(
                    id=child.id,
                    x=child.x + dx,
                    y=child.y + dy,
                    width=child.width,
                    height=child.height,
                )

    def _place_ports(
        self,
        layouts: dict[str, NodeLayout],
        parent: NodeLayout,
        ports: list,
        *,
        side: str,
    ) -> None:
        if not ports:
            return

        step = parent.height / (len(ports) + 1)
        for index, port in enumerate(ports, start=1):
            x = (
                parent.x - self.PORT_SIZE / 2
                if side == "left"
                else parent.x + parent.width - self.PORT_SIZE / 2
            )
            y = parent.y + index * step - self.PORT_SIZE / 2
            layouts[port.id] = NodeLayout(
                id=port.id,
                x=x,
                y=y,
                width=self.PORT_SIZE,
                height=self.PORT_SIZE,
            )
