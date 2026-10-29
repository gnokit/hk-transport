"""Journey search shared by the MTR and the buses.

Nodes are opaque integers. An edge is `(from, to, kind)`, where kind is

- `ride` — one stop along one trip, cost 0 transfers and 1 stop;
- `transfer` — the same place on another trip, cost 1 transfer and 0 stops.

Cost is the pair `(transfers, stops)`, compared in that order. A transfer is
given a weight larger than any route's stop count, so one integer weight
reproduces that order and the search can stay in a library.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

RIDE = "ride"
TRANSFER = "transfer"
_START = "start"
_END = "end"

# Larger than any real number of stops on one route, so one transfer always
# costs more than any number of stops.
_TRANSFER_WEIGHT = 10_000


@dataclass(frozen=True)
class Route:
    """One way to travel: the nodes in order, and the kind of each hop."""

    nodes: tuple[int, ...]
    kinds: tuple[str, ...]
    transfers: int
    rides: int


def journeys(
    node_count: int,
    edges: list[tuple[int, int, str]],
    starts: list[int],
    goals: set[int],
    k: int = 1,
) -> list[Route]:
    """Up to `k` ways from any start to any goal, cheapest first.

    Cheapest means fewest transfers, then fewest stops. `k` greater than one
    gives alternatives for a person to choose between; it does not rank them
    beyond that cost.
    """
    found: list[Route] = []
    if not starts or not goals:
        return found
    graph = nx.DiGraph()
    graph.add_nodes_from(range(node_count))
    for source, target, kind in edges:
        weight = _TRANSFER_WEIGHT if kind == TRANSFER else 1
        if graph.has_edge(source, target) and graph[source][target]["weight"] <= weight:
            continue
        graph.add_edge(source, target, weight=weight, kind=kind)
    source_node = node_count
    sink_node = node_count + 1
    for start in starts:
        graph.add_edge(source_node, start, weight=0, kind=_START)
    for goal in goals:
        graph.add_edge(goal, sink_node, weight=0, kind=_END)
    seen: set[tuple[int, ...]] = set()
    paths = nx.shortest_simple_paths(graph, source_node, sink_node, weight="weight")
    try:
        for path in paths:
            middle = tuple(path[1:-1])
            if not middle or middle in seen:
                continue
            seen.add(middle)
            kinds = tuple(
                graph[middle[index]][middle[index + 1]]["kind"]
                for index in range(len(middle) - 1)
            )
            found.append(
                Route(
                    nodes=middle,
                    kinds=kinds,
                    transfers=kinds.count(TRANSFER),
                    rides=kinds.count(RIDE),
                )
            )
            if len(found) >= k:
                break
    except nx.NetworkXNoPath:
        return found
    return found
