from __future__ import annotations

from collections import deque

Coordinate = tuple[float, float]


def max_component_elongation(
    all_coordinates: tuple[Coordinate, ...],
    failure_coordinates: tuple[Coordinate, ...],
) -> float | None:
    if not failure_coordinates:
        return None
    x_values = sorted({x for x, _ in all_coordinates})
    y_values = sorted({y for _, y in all_coordinates})
    x_axis = {value: index for index, value in enumerate(x_values)}
    y_axis = {value: index for index, value in enumerate(y_values)}
    grid = {(x_axis[x], y_axis[y]): (x, y) for x, y in failure_coordinates}
    remaining = set(grid)
    elongations: list[float] = []
    while remaining:
        start = remaining.pop()
        queue = deque([start])
        component = [grid[start]]
        while queue:
            x, y = queue.popleft()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor = (x + dx, y + dy)
                    if (dx or dy) and neighbor in remaining:
                        remaining.remove(neighbor)
                        queue.append(neighbor)
                        component.append(grid[neighbor])
        elongation = _elongation(component)
        if elongation is not None:
            elongations.append(elongation)
    return max(elongations) if elongations else None


def _elongation(points: list[Coordinate]) -> float | None:
    if len(points) < 2:
        return None
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    xx = sum((x - mean_x) ** 2 for x, _ in points) / len(points)
    yy = sum((y - mean_y) ** 2 for _, y in points) / len(points)
    xy = sum((x - mean_x) * (y - mean_y) for x, y in points) / len(points)
    discriminant = ((xx - yy) ** 2 + 4.0 * xy * xy) ** 0.5
    largest = (xx + yy + discriminant) / 2.0
    smallest = max(0.0, (xx + yy - discriminant) / 2.0)
    if largest == 0.0:
        return None
    return min(1.0, max(0.0, 1.0 - (smallest / largest) ** 0.5))
