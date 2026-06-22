from __future__ import annotations

from collections import deque
from typing import Any
import statistics

import pandas as pd

from .h3_assignment import h3_library


def grid_disk(cell: str, k: int = 1) -> set[str]:
    h3 = h3_library()
    if hasattr(h3, "grid_disk"):
        return set(h3.grid_disk(cell, int(k)))
    return set(h3.k_ring(cell, int(k)))


def ring1_neighbors(cell: str) -> set[str]:
    return grid_disk(cell, 1) - {cell}


def present_neighbor_map(cells: list[str] | set[str]) -> dict[str, list[str]]:
    present = set(map(str, cells))
    return {
        cell: sorted(ring1_neighbors(cell) & present)
        for cell in sorted(present)
    }


def connected_components(neighbor_map: dict[str, list[str]]) -> list[list[str]]:
    unseen = set(neighbor_map)
    components: list[list[str]] = []
    while unseen:
        start = unseen.pop()
        queue: deque[str] = deque([start])
        component = {start}
        while queue:
            current = queue.popleft()
            for neighbor in neighbor_map.get(current, []):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    return sorted(components, key=lambda c: (-len(c), c[0] if c else ""))


def neighbor_report(cells: list[str] | pd.Series,
                    minimum_present_neighbors: int = 1) -> dict[str, Any]:
    cell_list = sorted(set(map(str, cells)))
    neighbors = present_neighbor_map(cell_list)
    components = connected_components(neighbors)
    isolated = [cell for cell, ns in neighbors.items() if len(ns) < minimum_present_neighbors]
    component_sizes = [len(c) for c in components]
    size_distribution: dict[str, int] = {}
    for size in component_sizes:
        size_distribution[str(size)] = size_distribution.get(str(size), 0) + 1
    present_neighbor_counts = [len(ns) for ns in neighbors.values()]
    return {
        "status": "WARN" if len(components) > 1 or isolated else "PASS",
        "cell_count": len(cell_list),
        "number_of_cells": len(cell_list),
        "minimum_present_neighbors": minimum_present_neighbors,
        "isolated_cell_count": len(isolated),
        "isolated_cells": isolated[:1000],
        "component_count": len(components),
        "number_of_components": len(components),
        "largest_component_size": len(components[0]) if components else 0,
        "smallest_component_size": min(component_sizes) if component_sizes else 0,
        "median_component_size": statistics.median(component_sizes) if component_sizes else 0,
        "component_size_distribution": size_distribution,
        "average_present_neighbors": float(sum(present_neighbor_counts) / len(present_neighbor_counts)) if present_neighbor_counts else 0.0,
        "warnings": [
            code for code, condition in [
                ("SPATIAL_GRAPH_DISCONNECTED", len(components) > 1),
                ("SPATIAL_ISLANDS_PRESENT", bool(isolated)),
            ] if condition
        ],
        "neighbors": neighbors,
    }


def component_table(cells: list[str] | pd.Series,
                    minimum_present_neighbors: int = 1) -> pd.DataFrame:
    cell_list = sorted(set(map(str, cells)))
    neighbors = present_neighbor_map(cell_list)
    components = connected_components(neighbors)
    rows = []
    for component_id, component in enumerate(components, start=1):
        size = len(component)
        for cell in component:
            present_neighbor_count = len(neighbors[cell])
            rows.append({
                "h3_res10": cell,
                "spatial_component_id": component_id,
                "spatial_component_size": size,
                "present_neighbor_count": present_neighbor_count,
                "is_spatial_island": present_neighbor_count < minimum_present_neighbors,
                "spatial_test_status": "INSUFFICIENT_NEIGHBORS" if present_neighbor_count < minimum_present_neighbors else "PENDING",
            })
    return pd.DataFrame(rows)
