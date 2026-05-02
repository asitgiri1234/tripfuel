from __future__ import annotations

import math
from typing import List, Sequence, Tuple


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613  # mean Earth radius in miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def cumulative_miles_along_linestring(coords: Sequence[Sequence[float]]) -> List[float]:
    if not coords:
        return []
    cum: List[float] = [0.0]
    for i in range(1, len(coords)):
        a = coords[i - 1]
        b = coords[i]
        cum.append(cum[-1] + haversine_miles(a[1], a[0], b[1], b[0]))
    return cum


def _segment_project(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> Tuple[float, float, float]:
    """Project point p onto segment ab. Returns (t_clamped, proj_lon, proj_lat) with t in [0,1]."""
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    denom = abx * abx + aby * aby
    if denom <= 1e-18:
        return 0.0, ax, ay
    t = (apx * abx + apy * aby) / denom
    t = max(0.0, min(1.0, t))
    return t, ax + t * abx, ay + t * aby


def mile_marker_along_route(
    lon: float,
    lat: float,
    coords: Sequence[Sequence[float]],
    cum_miles: Sequence[float],
) -> float:
    """Approximate distance along the polyline (miles) to the nearest point on the route."""
    if len(coords) < 2:
        return 0.0
    best_d = float("inf")
    best_mile = 0.0
    for i in range(len(coords) - 1):
        a = coords[i]
        b = coords[i + 1]
        _, mx, my = _segment_project(lon, lat, a[0], a[1], b[0], b[1])
        d = haversine_miles(lat, lon, my, mx)
        seg_len = max(1e-9, cum_miles[i + 1] - cum_miles[i])
        t, _, _ = _segment_project(lon, lat, a[0], a[1], b[0], b[1])
        mile = cum_miles[i] + t * seg_len
        if d < best_d:
            best_d = d
            best_mile = mile
    return best_mile


def snap_lonlat_to_polyline(
    lon: float,
    lat: float,
    coords: Sequence[Sequence[float]],
) -> Tuple[float, float, float]:
    """Return (snapped_lon, snapped_lat, mile_marker) nearest to lon/lat."""
    if len(coords) < 2:
        return lon, lat, 0.0
    cum = cumulative_miles_along_linestring(coords)
    best_d = float("inf")
    best = (lon, lat, 0.0)
    for i in range(len(coords) - 1):
        a = coords[i]
        b = coords[i + 1]
        t, mx, my = _segment_project(lon, lat, a[0], a[1], b[0], b[1])
        d = haversine_miles(lat, lon, my, mx)
        seg_len = max(1e-9, cum[i + 1] - cum[i])
        mile = cum[i] + t * seg_len
        if d < best_d:
            best_d = d
            best = (mx, my, mile)
    return best[0], best[1], best[2]


def scale_cumulative_miles(cum: Sequence[float], target_total_miles: float) -> List[float]:
    if not cum:
        return []
    total = cum[-1]
    if total <= 1e-9:
        return [0.0 for _ in cum]
    s = target_total_miles / total
    return [c * s for c in cum]


def resample_mile_marker(mile: float, scaled_cum: Sequence[float], coords: Sequence[Sequence[float]]) -> Tuple[float, float]:
    """Map a mile marker to lon/lat along the polyline (linear interpolation on segments)."""
    if len(coords) < 2:
        return coords[0][0], coords[0][1]
    for i in range(len(scaled_cum) - 1):
        c0, c1 = scaled_cum[i], scaled_cum[i + 1]
        if mile <= c1 or i == len(scaled_cum) - 2:
            if c1 <= c0 + 1e-9:
                return coords[i][0], coords[i][1]
            t = (mile - c0) / (c1 - c0)
            t = max(0.0, min(1.0, t))
            a, b = coords[i], coords[i + 1]
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
    return coords[-1][0], coords[-1][1]


def point_distance_to_polyline_miles(lon: float, lat: float, coords: Sequence[Sequence[float]]) -> float:
    if len(coords) < 2:
        return haversine_miles(lat, lon, coords[0][1], coords[0][0])
    best = float("inf")
    for i in range(len(coords) - 1):
        a = coords[i]
        b = coords[i + 1]
        _, mx, my = _segment_project(lon, lat, a[0], a[1], b[0], b[1])
        best = min(best, haversine_miles(lat, lon, my, mx))
    return best

