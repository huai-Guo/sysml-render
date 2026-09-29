from __future__ import annotations

from dataclasses import asdict, dataclass, field

from graph_ir import DiagramIR


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
    """Deterministic container/port aware layout used by the Phase-0 prototype.

    This is intentionally replaceable. The production renderer can use ELK,
    but ProjectionEngine must not depend on the concrete layout engine.
    """

    ROOT_X = 40.0
    ROOT_Y = 40.0
    ROOT_HEADER = 52.0
    ROOT_PADDING = 60.0
    PART_WIDTH = 190.0
    PART_HEIGHT = 120.0
    PART_GAP = 90.0
    PORT_SIZE = 14.0

    def layout(self, ir: DiagramIR) -> LayoutResult:
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

        # Fallback for profile nodes not covered by the structure layout.
        unplaced = [
            node
            for node in ir.nodes
            if node.id not in layouts
        ]
        fallback_y = self.ROOT_Y + root_height + 40.0
        for index, node in enumerate(unplaced):
            layouts[node.id] = NodeLayout(
                id=node.id,
                x=self.ROOT_X + index * 180.0,
                y=fallback_y,
                width=150.0,
                height=70.0,
            )

        routes = []
        for edge in ir.edges:
            source = layouts[edge.source]
            target = layouts[edge.target]
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

        canvas_width = max(
            root_width + self.ROOT_X * 2,
            max(layout.x + layout.width for layout in layouts.values()) + 40,
        )
        canvas_height = max(
            self.ROOT_Y + root_height + 60,
            max(layout.y + layout.height for layout in layouts.values()) + 40,
        )

        return LayoutResult(
            width=canvas_width,
            height=canvas_height,
            nodes=list(layouts.values()),
            edges=routes,
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
