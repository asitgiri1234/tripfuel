# TripFuel (Django API)

Driving route + **minimum-money refueling plan** for trips inside the USA.

- **Routing / map geometry**: [OSRM public demo server](https://router.project-osrm.org/) — **one HTTP GET** per coordinate-based request (`geometries=geojson&overview=full`).
- **Optional geocoding**: [Nominatim](https://nominatim.org/) — **two HTTP GETs** when you send `start_address` / `end_address` (USA-only validation after geocode).
- **Fuel prices**: load from `data/fuel_prices.csv` (replace with your provided attachment; supports `latitude`/`longitude`/`price_per_gallon` plus optional `name`).
- **Vehicle**: **500 miles** max range, **10 MPG**, **50-gallon tank**, starts with a full tank.
- **Fuel optimizer**: Greedy look-ahead algorithm with **partial refueling** — buys only enough fuel to reach a cheaper station ahead, or fills to capacity when no cheaper station exists.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
python tools/generate_fuel_prices.py  # optional synthetic CSV if you don't have the attachment yet
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Optional (recommended by Nominatim usage policy):

```powershell
$env:TRIPFUEL_NOMINATIM_EMAIL="you@example.com"
```

## Fuel Optimization Algorithm

`routing/services/optimize.py` implements a production-level greedy + look-ahead strategy:

1. **Reachability scan** — at every stop, determine all stations ahead reachable with the fuel currently in the tank.
2. **Look-ahead pricing** — scan up to the full-tank range for the first station that is cheaper than the current one, and for the absolute cheapest station in that window.
3. **Partial vs. full fill decision**
   - If a cheaper station exists ahead → buy **only enough fuel to reach it**.
   - If no cheaper station exists ahead and the end is within range → buy **only enough fuel to finish**.
   - If no cheaper station exists and the end is beyond range → **fill the tank** and drive to the cheapest reachable station.
4. **Movement** — after refueling, move to the cheapest reachable station (or the end if reachable).

Key functions:
- `get_reachable_stations()` — stations ahead within current fuel range (no backtracking).
- `find_next_cheapest_station()` — first cheaper station and absolute cheapest within the look-ahead window.
- `calculate_required_fuel()` — gallons needed to cover a given distance without exceeding tank capacity.
- `simulate_fuel_journey()` — step-by-step simulation tracking position, fuel level, and purchases.

## API

`POST /api/v1/route/`

**Body (coordinates — 1 external routing call):**

```json
{
  "start_latitude": 41.8781,
  "start_longitude": -87.6298,
  "end_latitude": 39.7392,
  "end_longitude": -104.9903,
  "max_off_route_miles": 15
}
```

**Body (addresses — 2 geocode + 1 route):**

```json
{
  "start_address": "Chicago, IL",
  "end_address": "Denver, CO",
  "max_off_route_miles": 15
}
```

**Response highlights**

- `summary`: trip totals — `total_distance_miles`, `total_cost_usd`, `total_gallons`, `number_of_stops`.
- `fuel_stops`: array of purchases with `latitude`, `longitude`, `price_per_gallon`, `gallons_purchased`, `cost`, and `reason`:
  - `partial_fill_for_cheaper_station` — bought minimum fuel to reach a cheaper station ahead.
  - `full_fill_no_cheaper_ahead` — tank filled because all remaining stations are more expensive.
  - `partial_fill_for_end` — bought only enough fuel to reach the destination directly.
- `map.geojson`: GeoJSON `FeatureCollection` with the route `LineString` and `Point` features for each fuel purchase.
- `fuel.total_money_spent_usd`: sum of purchases along the route (starts with a full tank; only **paid** stops count).
- `fuel.trip_gallons_at_mpg`: total gallons implied by **distance ÷ 10 MPG** for the returned route.
- `external_api_usage`: counts OSRM / Nominatim HTTP requests for this call.

Import `postman/TripFuel.postman_collection.json` for ready-made requests.

## Tests

```bash
python manage.py test routing.tests
```

Covers reachability, look-ahead price scanning, fuel calculations, and full journey simulations including edge cases such as unreachable routes and partial fills for the destination.

## Notes for reviewers / Loom demo

- Show Postman `POST /api/v1/route/` with coordinates and expand `summary` + `fuel_stops`.
- Mention OSRM single call, CSV-driven prices, and the greedy look-ahead optimizer in `routing/services/optimize.py`.
- Highlight partial-refuel decisions (`partial_fill_for_cheaper_station` vs `full_fill_no_cheaper_ahead` vs `partial_fill_for_end`).
