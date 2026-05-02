from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

import requests


@dataclass(frozen=True)
class OsrmRouteResult:
    coordinates_lonlat: List[List[float]]  # GeoJSON order: [lon, lat]
    distance_meters: float
    duration_seconds: float
    raw: Dict[str, Any]


def fetch_route_osrm(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
    *,
    base_url: str = "https://router.project-osrm.org",
    timeout: float = 20.0,
    session: requests.Session | None = None,
) -> OsrmRouteResult:
    """
    Single OSRM Route request (driving profile).
    Public demo server: reasonable non-commercial use; ~1 req/s courtesy limit.
    """
    sess = session or requests.Session()
    coords = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    url = f"{base_url.rstrip('/')}/route/v1/driving/{coords}"
    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
    }
    headers = {"User-Agent": "TripFuel/1.0 (assignment demo; contact: local)"}
    r = sess.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(f"OSRM error: {data.get('code')!r} message={data.get('message')}")
    route = data["routes"][0]
    geom = route["geometry"]
    if geom.get("type") != "LineString":
        raise ValueError("Unexpected OSRM geometry type")
    coords_ll: Sequence[Sequence[float]] = geom["coordinates"]
    list_coords = [list(map(float, c)) for c in coords_ll]
    return OsrmRouteResult(
        coordinates_lonlat=list_coords,
        distance_meters=float(route["distance"]),
        duration_seconds=float(route["duration"]),
        raw=data,
    )
