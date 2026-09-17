import numpy as np
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from numba import njit

@dataclass
class FloodResult:
    flood_mask: np.ndarray
    water_depth: np.ndarray
    flooded_cells: int
    total_volume: float
    avg_depth: float
    max_depth: float
    min_elevation: float
    max_elevation: float
    iterations: int
    water_level: float


@njit
def _flood_fill_level(dem, start_x, start_y, water_level, cell_area):
    h, w = dem.shape

    visited = np.zeros((h, w), dtype=np.uint8)

    stack_x = np.empty(h * w, dtype=np.int32)
    stack_y = np.empty(h * w, dtype=np.int32)

    top = 0
    stack_x[top] = start_x
    stack_y[top] = start_y
    top += 1

    flooded_cells = 0
    total_volume = 0.0
    max_depth = 0.0
    min_elev = 1e9
    max_elev = -1e9

    iterations = 0

    while top > 0:
        top -= 1
        x = stack_x[top]
        y = stack_y[top]

        if visited[y, x]:
            continue

        elev = dem[y, x]

        if elev > water_level:
            continue

        visited[y, x] = 1
        flooded_cells += 1

        # статистика
        depth = water_level - elev
        total_volume += depth * cell_area

        if depth > max_depth:
            max_depth = depth

        if elev < min_elev:
            min_elev = elev
        if elev > max_elev:
            max_elev = elev

        # соседи (4-connectivity)
        if x + 1 < w and not visited[y, x + 1]:
            stack_x[top] = x + 1
            stack_y[top] = y
            top += 1

        if x - 1 >= 0 and not visited[y, x - 1]:
            stack_x[top] = x - 1
            stack_y[top] = y
            top += 1

        if y + 1 < h and not visited[y + 1, x]:
            stack_x[top] = x
            stack_y[top] = y + 1
            top += 1

        if y - 1 >= 0 and not visited[y - 1, x]:
            stack_x[top] = x
            stack_y[top] = y - 1
            top += 1

        iterations += 1

    return visited, flooded_cells, total_volume, max_depth, min_elev, max_elev, iterations


class FloodFiller:
    def __init__(self, dem: np.ndarray, cell_size: float = 1.0):
        self.dem = dem.astype(np.float32)
        self.height, self.width = dem.shape
        self.cell_size = cell_size
        self.cell_area = cell_size * cell_size


    def compute_flood(
        self,
        start_x: int,
        start_y: int,
        water_level: Optional[float] = None,
    ) -> FloodResult:

        if not (0 <= start_x < self.width and 0 <= start_y < self.height):
            raise ValueError("Start point outside DEM")

        start_h = self.dem[start_y, start_x]

        if water_level is None:
            raise ValueError("water_level required")

        if start_h > water_level:
            return self._empty_result(water_level)

        return self._run_level(start_x, start_y, water_level)


    def _run_level(self, start_x, start_y, water_level):

        mask, flooded_cells, total_volume, max_depth, min_elev, max_elev, iterations = _flood_fill_level(
            self.dem,
            start_x,
            start_y,
            water_level,
            self.cell_area,
        )

        water_depth = np.zeros_like(self.dem, dtype=np.float32)
        flooded = mask == 1
        water_depth[flooded] = water_level - self.dem[flooded]

        avg_depth = total_volume / (flooded_cells * self.cell_area) if flooded_cells > 0 else 0

        return FloodResult(
            flood_mask=flooded,
            water_depth=water_depth,
            flooded_cells=int(flooded_cells),
            total_volume=float(total_volume),
            avg_depth=float(avg_depth),
            max_depth=float(max_depth),
            min_elevation=float(min_elev),
            max_elevation=float(max_elev),
            iterations=int(iterations),
            water_level=float(water_level),
        )


    def _empty_result(self, water_level):
        return FloodResult(
            flood_mask=np.zeros_like(self.dem, dtype=bool),
            water_depth=np.zeros_like(self.dem, dtype=np.float32),
            flooded_cells=0,
            total_volume=0.0,
            avg_depth=0.0,
            max_depth=0.0,
            min_elevation=0.0,
            max_elevation=0.0,
            iterations=0,
            water_level=water_level,
        )
