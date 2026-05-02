"""
Generate a dense synthetic fuel price dataset for development/demo.

Replace data/fuel_prices.csv with your provided attachment if column names include:
latitude/longitude (or lat/lon) and price fields (price_per_gallon, price, etc.).
"""

from __future__ import annotations

import csv
import random
from pathlib import Path


def main() -> None:
    random.seed(7)
    root = Path(__file__).resolve().parents[1]
    out = root / "data" / "fuel_prices.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    anchors = [
        (47.6062, -122.3321, "Seattle WA"),
        (45.5152, -122.6784, "Portland OR"),
        (37.7749, -122.4194, "San Francisco CA"),
        (34.0522, -118.2437, "Los Angeles CA"),
        (32.7157, -117.1611, "San Diego CA"),
        (36.1699, -115.1398, "Las Vegas NV"),
        (39.7392, -104.9903, "Denver CO"),
        (44.9778, -93.2650, "Minneapolis MN"),
        (41.8781, -87.6298, "Chicago IL"),
        (42.3314, -83.0458, "Detroit MI"),
        (39.0997, -94.5786, "Kansas City MO"),
        (29.7604, -95.3698, "Houston TX"),
        (32.7767, -96.7970, "Dallas TX"),
        (25.7617, -80.1918, "Miami FL"),
        (33.7490, -84.3880, "Atlanta GA"),
        (38.9072, -77.0369, "Washington DC"),
        (40.7128, -74.0060, "New York NY"),
        (42.3601, -71.0589, "Boston MA"),
        (39.9526, -75.1652, "Philadelphia PA"),
    ]

    rows: list[tuple[float, float, float, str]] = []

    # highway-ish interpolation between hubs
    for i in range(len(anchors)):
        for j in range(i + 1, len(anchors)):
            la1, lo1, _ = anchors[i]
            la2, lo2, _ = anchors[j]
            if abs(la1 - la2) + abs(lo1 - lo2) < 8:
                continue
            for t in (0.05, 0.12, 0.2, 0.28, 0.36, 0.44, 0.52, 0.6, 0.68, 0.76, 0.84, 0.92):
                lat = la1 + (la2 - la1) * t + random.uniform(-0.35, 0.35)
                lon = lo1 + (lo2 - lo1) * t + random.uniform(-0.45, 0.45)
                price = round(random.uniform(2.65, 4.95), 3)
                rows.append((lat, lon, price, f"Hub corridor stop ({i}-{j})"))

    # random nationwide fillers
    for k in range(350):
        lat = random.uniform(25.0, 48.5)
        lon = random.uniform(-123.5, -69.0)
        price = round(random.uniform(2.75, 4.85), 3)
        rows.append((lat, lon, price, f"Regional station #{k}"))

    # anchor stations (usually denser pricing diversity near metros)
    for lat, lon, name in anchors:
        for _ in range(6):
            rows.append(
                (
                    lat + random.uniform(-0.6, 0.6),
                    lon + random.uniform(-0.8, 0.8),
                    round(random.uniform(2.85, 4.75), 3),
                    f"{name} area",
                )
            )

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["latitude", "longitude", "price_per_gallon", "name"])
        w.writeheader()
        for lat, lon, price, name in rows:
            w.writerow(
                {
                    "latitude": f"{lat:.6f}",
                    "longitude": f"{lon:.6f}",
                    "price_per_gallon": f"{price:.3f}",
                    "name": name,
                }
            )

    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
