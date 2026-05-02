# TripFuel (Django API)

Driving route + **minimum‑money refueling plan** for trips inside the USA.

- **Routing / map geometry**: [OSRM public demo server](https://router.project-osrm.org/) — **one HTTP GET** per coordinate‑based request (`geometries=geojson&overview=full`).
- **Optional geocoding**: [Nominatim](https://nominatim.org/) — **two HTTP GETs** when you send `start_address` / `end_address` (USA‑only validation after geocode).
- **Fuel prices**: load from `data/fuel_prices.csv` (replace with your provided attachment; supports `latitude`/`longitude`/`price_per_gallon` plus optional `name`).
- **Vehicle**: **500 miles** max range between fills, **10 MPG** for gallon math.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
python tools/generate_fuel_prices.py  # optional synthetic CSV if you don’t have the attachment yet
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Optional (recommended by Nominatim usage policy):

```powershell
$env:TRIPFUEL_NOMINATIM_EMAIL="you@example.com"
```

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

- `map.geojson`: GeoJSON `FeatureCollection` with the route `LineString` and `Point` features for each fuel purchase.
- `fuel.total_money_spent_usd`: sum of purchases along the route (starts with a full tank; only **paid** stops count).
- `fuel.trip_gallons_at_mpg`: total gallons implied by **distance ÷ 10 MPG** for the returned route.
- `external_api_usage`: counts OSRM / Nominatim HTTP requests for this call.

Import `postman/TripFuel.postman_collection.json` for ready‑made requests.

## Notes for reviewers / Loom demo

- Show Postman `POST /api/v1/route/` with coordinates and expand `map.geojson` + `fuel.stops`.
- Mention OSRM single call, CSV‑driven prices, and the purchase optimizer in `routing/services/optimize.py`.
