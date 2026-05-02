from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from django.conf import settings

from routing.services.geometry import (
    mile_marker_along_route,
    point_distance_to_polyline_miles,
    scale_cumulative_miles,
    snap_lonlat_to_polyline,
)


@dataclass(frozen=True)
class FuelStation:
    latitude: float
    longitude: float
    price_per_gallon: float
    name: str
    mile_marker: float
    distance_off_route_miles: float


def _to_float(x: str) -> float:
    return float(x.strip())


def load_fuel_rows(csv_path: Path) -> List[Tuple[float, float, float, str]]:
    rows: List[Tuple[float, float, float, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return rows
        fields = {n.strip().lower(): n for n in reader.fieldnames}
        lat_k = _pick(fields, ("latitude", "lat"))
        lon_k = _pick(fields, ("longitude", "lon", "lng"))
        price_k = _pick(
            fields,
            ("price_per_gallon", "price", "usd_per_gallon", "regular", "fuel_price"),
        )
        name_k = None
        for cand in ("name", "station", "label", "location"):
            if cand in fields:
                name_k = fields[cand]
                break
        for row in reader:
            try:
                lat = _to_float(row[lat_k])
                lon = _to_float(row[lon_k])
                price = _to_float(row[price_k])
            except (KeyError, ValueError):
                continue
            name = row.get(name_k, "").strip() if name_k else ""
            if not name:
                name = f"Station ({lat:.3f},{lon:.3f})"
            rows.append((lat, lon, price, name))
    return rows


def _pick(field_map: dict[str, str], candidates: Iterable[str]) -> str:
    for c in candidates:
        if c in field_map:
            return field_map[c]
    raise KeyError(f"Missing required column; tried {candidates}")


@lru_cache(maxsize=1)
def get_all_stations_cached(csv_path_str: str) -> Tuple[Tuple[float, float, float, str], ...]:
    p = Path(csv_path_str)
    if not p.is_file():
        return tuple()
    return tuple(load_fuel_rows(p))


def stations_near_polyline(
    coords_lonlat: Sequence[Sequence[float]],
    *,
    total_route_miles: float,
    max_off_route_miles: float = 15.0,
) -> List[FuelStation]:
    csv_path = Path(settings.FUEL_PRICES_CSV)
    raw = get_all_stations_cached(str(csv_path.resolve()))
    if not raw:
        return []

    from routing.services.geometry import cumulative_miles_along_linestring

    cum = cumulative_miles_along_linestring(coords_lonlat)
    scaled = scale_cumulative_miles(cum, total_route_miles)

    out: List[FuelStation] = []
    for lat, lon, price, name in raw:
        off = point_distance_to_polyline_miles(lon, lat, coords_lonlat)
        if off > max_off_route_miles:
            continue
        slon, slat, _ = snap_lonlat_to_polyline(lon, lat, coords_lonlat)
        mm = mile_marker_along_route(lon, lat, coords_lonlat, scaled)
        out.append(
            FuelStation(
                latitude=slat,
                longitude=slon,
                price_per_gallon=float(price),
                name=name,
                mile_marker=float(mm),
                distance_off_route_miles=float(off),
            )
        )
    out.sort(key=lambda s: s.mile_marker)
    return _dedupe_by_mile(out)


def _dedupe_by_mile(stations: List[FuelStation], mile_eps: float = 2.0) -> List[FuelStation]:
    """Keep cheapest station when several map to nearly the same route position."""
    if not stations:
        return []
    merged: List[FuelStation] = []
    cur = stations[0]
    for s in stations[1:]:
        if abs(s.mile_marker - cur.mile_marker) <= mile_eps:
            if s.price_per_gallon < cur.price_per_gallon:
                cur = s
        else:
            merged.append(cur)
            cur = s
    merged.append(cur)
    return merged
