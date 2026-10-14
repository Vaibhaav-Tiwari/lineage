"""The unit every graph tool returns: a small subgraph plus a compact payload
for the LLM. Answers are rendered from merged Fragments (evidence subgraphs)."""

from dataclasses import dataclass, field
from typing import TypedDict


class Node(TypedDict):
    id: str
    label: str
    props: dict


class Edge(TypedDict):
    src: str
    dst: str
    type: str
    props: dict


@dataclass
class Fragment:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def merge(self, other: "Fragment") -> "Fragment":
        nodes = {n["id"]: n for n in self.nodes}
        for n in other.nodes:
            nodes.setdefault(n["id"], n)
        edges = {(e["src"], e["dst"], e["type"]): e for e in self.edges}
        for e in other.edges:
            edges.setdefault((e["src"], e["dst"], e["type"]), e)
        return Fragment(list(nodes.values()), list(edges.values()), {**self.meta, **other.meta})

    def ids(self) -> set[str]:
        return {n["id"] for n in self.nodes}

    def to_json(self) -> dict:
        return {"nodes": self.nodes, "edges": self.edges}
