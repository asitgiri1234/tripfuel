from __future__ import annotations

from typing import Any, Dict, List

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.serializers import TripFuelRequestSerializer
from routing.services.fuel_stations import stations_near_polyline
from routing.services.geocode import geocode_nominatim
from routing.services.optimize import build_route_nodes, optimize_fuel_stops
from routing.services.osrm import fetch_route_osrm
from routing.validators import in_usa


class TripFuelRouteView(APIView):
    """
    POST /api/v1/route/

    Computes a driving route (OSRM) and a minimum-cost refueling plan using fuel prices from CSV.
    """

    def post(self, request):
        ser = TripFuelRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        session = requests.Session()
        external = {"routing_requests": 0, "geocoding_requests": 0}

        if data.get("start_address"):
            email = getattr(settings, "NOMINATIM_EMAIL", None)
            s = geocode_nominatim(data["start_address"], session=session, email=email)
            external["geocoding_requests"] += 1
            e = geocode_nominatim(data["end_address"], session=session, email=email)
            external["geocoding_requests"] += 1
            if not in_usa(s.latitude, s.longitude) or not in_usa(e.latitude, e.longitude):
                return Response(
                    {"detail": "Both ends must resolve to locations inside the USA."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            start_lat, start_lon = s.latitude, s.longitude
            end_lat, end_lon = e.latitude, e.longitude
            start_label = s.display_name
            end_label = e.display_name
        else:
            start_lat = float(data["start_latitude"])
            start_lon = float(data["start_longitude"])
            end_lat = float(data["end_latitude"])
            end_lon = float(data["end_longitude"])
            start_label = f"{start_lat:.5f},{start_lon:.5f}"
            end_label = f"{end_lat:.5f},{end_lon:.5f}"

        try:
            route = fetch_route_osrm(
                start_lon,
                start_lat,
                end_lon,
                end_lat,
                base_url=settings.OSRM_BASE_URL,
                session=session,
            )
        except Exception as exc:
            return Response({"detail": f"Routing failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        external["routing_requests"] += 1

        coords = route.coordinates_lonlat
        distance_miles = route.distance_meters / 1609.344

        corridor = float(data.get("max_off_route_miles", 15.0))
        nearby = stations_near_polyline(
            coords,
            total_route_miles=distance_miles,
            max_off_route_miles=corridor,
        )

        nodes = build_route_nodes(
            start_lon,
            start_lat,
            end_lon,
            end_lat,
            distance_miles,
            nearby,
        )

        try:
            opt = optimize_fuel_stops(
                nodes,
                max_range_miles=float(settings.VEHICLE_RANGE_MILES),
                mpg=float(settings.VEHICLE_MPG),
            )
        except Exception as exc:
            return Response(
                {
                    "detail": str(exc),
                    "hint": "Try increasing max_off_route_miles slightly or adding more stations to data/fuel_prices.csv.",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        geojson = self._build_geojson(coords, opt.purchases)

        gallons_from_purchases = float(opt.total_gallons_purchased)
        total_cost = float(opt.total_cost_usd)

        # Driving fuel consumption for whole trip at stated MPG (reporting).
        trip_gallons_total = distance_miles / float(settings.VEHICLE_MPG)

        resp = {
            "start": {"label": start_label, "latitude": start_lat, "longitude": start_lon},
            "end": {"label": end_label, "latitude": end_lat, "longitude": end_lon},
            "routing": {
                "distance_miles": round(distance_miles, 3),
                "duration_seconds": round(route.duration_seconds, 3),
                "provider": "OSRM",
                "osrm_profile": "driving",
            },
            "vehicle": {
                "miles_per_gallon": float(settings.VEHICLE_MPG),
                "max_range_miles": float(settings.VEHICLE_RANGE_MILES),
                "assumption": "Start with a full tank; spend counts fuel bought along the route.",
            },
            "fuel": {
                "total_money_spent_usd": total_cost,
                "total_gallons_purchased": gallons_from_purchases,
                "trip_gallons_at_mpg": round(trip_gallons_total, 3),
                "stops": [
                    {
                        "mile_marker": p.mile_marker,
                        "latitude": p.latitude,
                        "longitude": p.longitude,
                        "name": p.station_name,
                        "price_per_gallon_usd": p.price_per_gallon,
                        "gallons": p.gallons,
                        "cost_usd": p.cost_usd,
                        "reason": p.reason,
                    }
                    for p in opt.purchases
                ],
            },
            "summary": {
                "total_distance_miles": round(distance_miles, 3),
                "total_cost_usd": total_cost,
                "total_gallons": gallons_from_purchases,
                "number_of_stops": len(opt.purchases),
            },
            "fuel_stops": [
                {
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "price_per_gallon": p.price_per_gallon,
                    "gallons_purchased": p.gallons,
                    "cost": p.cost_usd,
                    "reason": p.reason,
                }
                for p in opt.purchases
            ],
            "map": {
                "geojson": geojson,
                "openstreetmap": {
                    "directions_url": (
                        f"https://www.openstreetmap.org/directions?"
                        f"engine=fossgis_osrm_car&route={start_lat}%2C{start_lon}%3B{end_lat}%2C{end_lon}"
                    ),
                },
            },
            "external_api_usage": {
                "routing_http_requests": external["routing_requests"],
                "geocoding_http_requests": external["geocoding_requests"],
                "notes": "Target is 1 routing request; +2 geocoding requests only when using addresses.",
            },
            "meta": {
                "fuel_station_candidates_near_route": len(nearby),
                "fuel_prices_csv": str(settings.FUEL_PRICES_CSV),
            },
        }
        return Response(resp)

    def _build_geojson(self, coords_lonlat: List[List[float]], purchases) -> Dict[str, Any]:
        features: List[Dict[str, Any]] = [
            {
                "type": "Feature",
                "properties": {"kind": "route"},
                "geometry": {"type": "LineString", "coordinates": coords_lonlat},
            }
        ]
        for idx, p in enumerate(purchases, start=1):
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "kind": "fuel_stop",
                        "stop_index": idx,
                        "name": p.station_name,
                        "gallons": p.gallons,
                        "cost_usd": p.cost_usd,
                        "price_per_gallon_usd": p.price_per_gallon,
                        "mile_marker": p.mile_marker,
                        "reason": p.reason,
                    },
                    "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
                }
            )
        return {"type": "FeatureCollection", "features": features}
