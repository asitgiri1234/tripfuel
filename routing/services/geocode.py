from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


@dataclass(frozen=True)
class GeocodeHit:
    latitude: float
    longitude: float
    display_name: str
    raw: Dict[str, Any]


def geocode_nominatim(
    query: str,
    *,
    timeout: float = 15.0,
    session: requests.Session | None = None,
    email: Optional[str] = None,
) -> GeocodeHit:
    """
    OpenStreetMap Nominatim (free). Use a descriptive User-Agent per usage policy.
    Optional TRIPFUEL_NOMINATIM_EMAIL can be set for higher courtesy limits.
    """
    sess = session or requests.Session()
    url = "https://nominatim.openstreetmap.org/search"
    params: Dict[str, Any] = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 1,
    }
    if email:
        params["email"] = email
    headers = {"User-Agent": "TripFuel/1.0 (course assignment; https://example.local)"}
    r = sess.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise ValueError(f"No geocoding results for: {query!r}")
    hit = rows[0]
    lat = float(hit["lat"])
    lon = float(hit["lon"])
    cc = (hit.get("address") or {}).get("country_code", "").lower()
    if cc and cc != "us":
        raise ValueError(f"Location is not in the USA (country_code={cc!r}): {query!r}")
    return GeocodeHit(
        latitude=lat,
        longitude=lon,
        display_name=str(hit.get("display_name", query)),
        raw=hit,
    )
