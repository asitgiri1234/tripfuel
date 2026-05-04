from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from routing.services.fuel_stations import FuelStation

logger = logging.getLogger(__name__)

EPS = 1e-9
FALLBACK_BUFFER_MILES = 50.0  # allow travel slightly beyond rated max range


@dataclass(frozen=True)
class RouteNode:
    mile: float
    latitude: float
    longitude: float
    price_per_gallon: Optional[float]  # None for start/end
    name: str
    kind: str  # start | station | end


@dataclass(frozen=True)
class FuelPurchase:
    mile_marker: float
    latitude: float
    longitude: float
    station_name: str
    price_per_gallon: float
    gallons: float
    cost_usd: float
    reason: str


@dataclass(frozen=True)
class OptimizeResult:
    total_cost_usd: float
    total_gallons_purchased: float
    purchases: Tuple[FuelPurchase, ...]
    nodes: Tuple[RouteNode, ...]


def build_route_nodes(
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
    total_miles: float,
    stations: Sequence[FuelStation],
) -> Tuple[RouteNode, ...]:
    nodes: List[RouteNode] = [
        RouteNode(
            mile=0.0,
            latitude=start_lat,
            longitude=start_lon,
            price_per_gallon=None,
            name="Start",
            kind="start",
        )
    ]
    for s in stations:
        if s.mile_marker <= 0.01 or s.mile_marker >= total_miles - 0.01:
            continue
        nodes.append(
            RouteNode(
                mile=float(s.mile_marker),
                latitude=float(s.latitude),
                longitude=float(s.longitude),
                price_per_gallon=float(s.price_per_gallon),
                name=s.name,
                kind="station",
            )
        )
    nodes.append(
        RouteNode(
            mile=float(total_miles),
            latitude=end_lat,
            longitude=end_lon,
            price_per_gallon=None,
            name="Finish",
            kind="end",
        )
    )
    nodes.sort(key=lambda x: (x.mile, 0 if x.kind != "end" else 1))
    return tuple(nodes)


def get_reachable_stations(
    nodes: Sequence[RouteNode],
    *,
    current_index: int,
    current_fuel_gallons: float,
    mpg: float,
) -> List[int]:
    """Return station indices ahead reachable with current fuel (no backtracking)."""
    cur_mile = float(nodes[current_index].mile)
    max_reach = cur_mile + current_fuel_gallons * mpg + EPS
    out: List[int] = []
    for idx in range(current_index + 1, len(nodes)):
        n = nodes[idx]
        if n.mile > max_reach:
            break
        if n.kind == "station":
            out.append(idx)
    return out


def find_next_cheapest_station(
    nodes: Sequence[RouteNode],
    *,
    current_index: int,
    max_reach_miles: float,
    current_price: float,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Scan stations ahead up to max_reach_miles and return:
      - first cheaper-than-current station index (look-ahead trigger)
      - absolute cheapest station index in that reachable window
    """
    first_cheaper_idx: Optional[int] = None
    cheapest_idx: Optional[int] = None
    cheapest_price = float("inf")
    for idx in range(current_index + 1, len(nodes)):
        n = nodes[idx]
        if n.mile > max_reach_miles + EPS:
            break
        if n.kind != "station" or n.price_per_gallon is None:
            continue
        p = float(n.price_per_gallon)
        if first_cheaper_idx is None and p + EPS < current_price:
            first_cheaper_idx = idx
        if p + EPS < cheapest_price:
            cheapest_price = p
            cheapest_idx = idx
    return first_cheaper_idx, cheapest_idx


def calculate_required_fuel(
    *,
    current_fuel_gallons: float,
    distance_miles: float,
    mpg: float,
    tank_capacity_gallons: float,
) -> float:
    """Gallons to buy so current fuel can cover distance_miles."""
    need = max(0.0, (distance_miles / mpg) - current_fuel_gallons)
    return max(0.0, min(need, tank_capacity_gallons - current_fuel_gallons))


def simulate_fuel_journey(
    nodes: Sequence[RouteNode],
    *,
    tank_capacity_gallons: float,
    mpg: float,
    initial_fuel_gallons: float,
) -> OptimizeResult:
    """
    Greedy look-ahead fuel simulation.

    Decision logic at each stop:
      1. Scan ahead up to full-tank range for price comparison.
      2. If a cheaper station exists ahead:
         -- Buy only enough fuel to reach that cheaper station.
      3. If no cheaper station exists ahead:
         -- If the trip end is within full-tank range, buy only enough to finish.
         -- Otherwise, fill the tank to capacity (minimizing purchases at
            higher-priced stations further ahead) and travel to the cheapest
            reachable station.
    """
    if len(nodes) < 2:
        return OptimizeResult(0.0, 0.0, tuple(), tuple(nodes))

    current_index = 0
    fuel_gallons = float(initial_fuel_gallons)
    purchases: List[FuelPurchase] = []

    end_idx = len(nodes) - 1
    end_mile = float(nodes[end_idx].mile)

    # Short trip: we can reach the finish without any fuel purchases.
    if end_mile <= fuel_gallons * mpg + EPS:
        return OptimizeResult(0.0, 0.0, tuple(), tuple(nodes))

    safety = 0
    while current_index < end_idx:
        safety += 1
        if safety > 10000:
            raise ValueError("Fuel simulation exceeded safe loop count.")

        cur = nodes[current_index]
        cur_mile = float(cur.mile)
        remaining_to_end = end_mile - cur_mile

        # If we can already reach the end with the fuel in the tank, we're done.
        if remaining_to_end <= fuel_gallons * mpg + EPS:
            break

        # ------------------------------------------------------------------
        # PURCHASE DECISION (only at fuel stations, not at start/end)
        # ------------------------------------------------------------------
        if cur.kind == "station" and cur.price_per_gallon is not None:
            cur_price = float(cur.price_per_gallon)
            # Maximum distance we could possibly cover from here with a full tank.
            max_reach_from_here = cur_mile + tank_capacity_gallons * mpg

            # Look ahead within full-tank window:
            #   first_cheaper_idx -> first station encountered that is cheaper than current
            #   cheapest_idx      -> absolute cheapest station in that window
            first_cheaper_idx, cheapest_idx = find_next_cheapest_station(
                nodes,
                current_index=current_index,
                max_reach_miles=max_reach_from_here,
                current_price=cur_price,
            )

            if first_cheaper_idx is not None:
                # A cheaper station lies ahead. Purchase the minimum amount needed
                # to reach it, preserving tank capacity for the cheaper fuel.
                target_distance = float(nodes[first_cheaper_idx].mile - cur_mile)
                buy_gallons = calculate_required_fuel(
                    current_fuel_gallons=fuel_gallons,
                    distance_miles=target_distance,
                    mpg=mpg,
                    tank_capacity_gallons=tank_capacity_gallons,
                )
                reason = "partial_fill_for_cheaper_station"
            else:
                # No cheaper station ahead within full-tank range.
                # Determine the most useful destination we can target.
                if end_mile <= max_reach_from_here + EPS:
                    # The end is reachable without stopping at any intermediate
                    # (more expensive) station. Buy only what we need to finish.
                    target_distance = remaining_to_end
                    buy_gallons = calculate_required_fuel(
                        current_fuel_gallons=fuel_gallons,
                        distance_miles=target_distance,
                        mpg=mpg,
                        tank_capacity_gallons=tank_capacity_gallons,
                    )
                    reason = "partial_fill_for_end"
                elif cheapest_idx is not None:
                    # We must stop at a more expensive station. Fill up now so we
                    # minimise the number of future purchases at higher prices.
                    buy_gallons = max(0.0, tank_capacity_gallons - fuel_gallons)
                    reason = "full_fill_no_cheaper_ahead"
                else:
                    # No stations ahead and the end is beyond range.
                    raise ValueError(
                        "No station reachable within full tank range from current position."
                    )

            if buy_gallons > EPS:
                buy_gallons = round(buy_gallons, 3)
                cost = round(buy_gallons * cur_price, 2)
                purchases.append(
                    FuelPurchase(
                        mile_marker=cur_mile,
                        latitude=float(cur.latitude),
                        longitude=float(cur.longitude),
                        station_name=cur.name,
                        price_per_gallon=cur_price,
                        gallons=buy_gallons,
                        cost_usd=cost,
                        reason=reason,
                    )
                )
                fuel_gallons += buy_gallons

        if fuel_gallons <= EPS:
            raise ValueError(
                "No station is reachable with current fuel; route is infeasible "
                "with provided station coverage."
            )

        # ------------------------------------------------------------------
        # MOVEMENT: choose the next node to drive to with the fuel on hand.
        # ------------------------------------------------------------------
        reachable_stations = get_reachable_stations(
            nodes,
            current_index=current_index,
            current_fuel_gallons=fuel_gallons,
            mpg=mpg,
        )

        max_reach_now = cur_mile + fuel_gallons * mpg
        used_fallback = False
        if end_mile <= max_reach_now + EPS:
            # End is reachable -- head straight for it.
            target_idx = end_idx
        else:
            if not reachable_stations:
                # --------------------------------------------------------------
                # FALLBACK: no station is reachable with the fuel currently in
                # the tank. Look for the nearest station ahead, even if it is
                # slightly beyond the vehicle's rated max range.
                # --------------------------------------------------------------
                nearest_forward_idx: Optional[int] = None
                nearest_forward_distance = float("inf")
                for idx in range(current_index + 1, len(nodes)):
                    n = nodes[idx]
                    if n.kind == "station":
                        dist = float(n.mile - cur_mile)
                        if dist < nearest_forward_distance:
                            nearest_forward_distance = dist
                            nearest_forward_idx = idx

                if nearest_forward_idx is not None:
                    max_range_with_fallback = (
                        fuel_gallons * mpg + FALLBACK_BUFFER_MILES
                    )
                    if nearest_forward_distance <= max_range_with_fallback + EPS:
                        logger.warning(
                            "[FUEL FALLBACK] No station reachable within normal range. "
                            "Selecting nearest forward station at %.2f mi (buffer: %.2f mi).",
                            nearest_forward_distance,
                            FALLBACK_BUFFER_MILES,
                        )
                        target_idx = nearest_forward_idx
                        used_fallback = True
                    else:
                        raise ValueError(
                            f"No station reachable within remaining fuel range. "
                            f"Nearest station is {nearest_forward_distance:.1f} miles ahead."
                        )
                else:
                    raise ValueError(
                        "No station is reachable within remaining fuel range."
                    )
            else:
                # Greedy move: among all reachable stations, pick the cheapest price.
                target_idx = min(
                    reachable_stations,
                    key=lambda i: float(nodes[i].price_per_gallon or float("inf")),
                )

        travel = float(nodes[target_idx].mile - cur_mile)
        required = travel / mpg
        if not used_fallback and required > fuel_gallons + EPS:
            raise ValueError("Insufficient fuel to reach selected next stop.")

        fuel_gallons = max(0.0, fuel_gallons - required)
        current_index = target_idx

    total_gallons = round(sum(p.gallons for p in purchases), 3)
    total_cost = round(sum(p.cost_usd for p in purchases), 2)

    expected_fuel = end_mile / mpg
    logger.info(
        "[FUEL DEBUG] initial=%.3f | total_distance=%.2f mi | expected_fuel=%.3f gal | "
        "total_gallons_purchased=%.3f gal",
        initial_fuel_gallons,
        end_mile,
        expected_fuel,
        total_gallons,
    )

    return OptimizeResult(
        total_cost_usd=total_cost,
        total_gallons_purchased=total_gallons,
        purchases=tuple(purchases),
        nodes=tuple(nodes),
    )


def optimize_fuel_stops(
    nodes: Sequence[RouteNode],
    *,
    max_range_miles: float = 500.0,
    mpg: float = 10.0,
    initial_fuel_gallons: float = 20.0,
) -> OptimizeResult:
    tank_capacity = float(max_range_miles) / float(mpg)
    return simulate_fuel_journey(
        nodes,
        tank_capacity_gallons=tank_capacity,
        mpg=float(mpg),
        initial_fuel_gallons=initial_fuel_gallons,
    )
