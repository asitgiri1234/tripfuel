from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from routing.services.fuel_stations import FuelStation


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


State = Tuple[int, int]  # node_index, remaining_range in tenths of a mile (0..5000)


def _tank_capacity_tenths(max_range_miles: float) -> int:
    """Maximum drivable range stored in tank, expressed in tenths of a mile."""
    return max(0, min(5000, int(round(float(max_range_miles) * 10.0))))


def _consumption_tenths(distance_miles: float) -> int:
    """Fuel range consumed when driving distance_miles (must NOT clamp to tank size)."""
    return max(0, int(round(float(distance_miles) * 10.0)))


def optimize_fuel_stops(
    nodes: Sequence[RouteNode],
    *,
    max_range_miles: float = 500.0,
    mpg: float = 10.0,
) -> OptimizeResult:
    """
    Minimum-cost fuel purchases for a 1D route.

    Remaining driving range is tracked in 0.1 mile increments up to max_range_miles.
    Driving d miles consumes d miles of remaining range. Buying g gallons adds 10*g miles
    of range (MPG=10), capped by the tank (max_range_miles total range per fill level).
    """
    _ = mpg  # MPG is implicit via miles-per-gallon mapping used by the caller for reporting.

    if len(nodes) < 2:
        return OptimizeResult(0.0, 0.0, tuple(), tuple(nodes))

    max_t = _tank_capacity_tenths(float(max_range_miles))
    n = len(nodes)
    end_i = n - 1

    inf = float("inf")
    best: Dict[State, float] = {}
    pred: Dict[State, Tuple[Optional[State], str, dict]] = {}

    start_state: State = (0, max_t)
    best[start_state] = 0.0
    pred[start_state] = (None, "start", {})

    heap: List[Tuple[float, int, int]] = [(0.0, start_state[0], start_state[1])]

    goal_state: Optional[State] = None
    goal_cost = inf

    def relax(nxt: State, cost: float, prev: Optional[State], kind: str, meta: dict) -> None:
        nonlocal goal_cost, goal_state
        old = best.get(nxt, inf)
        if cost + 1e-9 < old:
            best[nxt] = cost
            pred[nxt] = (prev, kind, meta)
            heapq.heappush(heap, (cost, nxt[0], nxt[1]))
            if nxt[0] == end_i:
                if cost < goal_cost:
                    goal_cost = cost
                    goal_state = nxt

    while heap:
        cost, i, fm_t = heapq.heappop(heap)
        st: State = (i, fm_t)
        if best.get(st, inf) + 1e-9 < cost:
            continue

        node = nodes[i]

        # Buy fuel at stations (integer gallons).
        if node.price_per_gallon is not None and node.kind != "end":
            price = float(node.price_per_gallon)
            max_add_t = max_t - fm_t
            max_g = int(math.floor(max_add_t / 100.0 + 1e-9))
            for g in range(1, max_g + 1):
                new_fm = fm_t + 100 * g
                if new_fm > max_t:
                    break
                relax((i, new_fm), cost + g * price, st, "buy", {"gallons": float(g), "price": price})

        # Drive downstream while range allows.
        for j in range(i + 1, n):
            dm = float(nodes[j].mile - node.mile)
            if dm <= 0:
                continue
            need = _consumption_tenths(dm)
            if need > fm_t + 1:
                continue
            new_fm = fm_t - need
            new_fm = max(0, min(max_t, new_fm))
            relax((j, new_fm), cost, st, "drive", {"to": j, "miles": dm})

    if goal_state is None or math.isinf(best.get(goal_state, inf)):
        raise ValueError(
            "No feasible fuel plan: expand fuel station coverage along the route (CSV / corridor width)."
        )

    purchases_rev: List[FuelPurchase] = []
    cur: Optional[State] = goal_state
    for _ in range(100000):
        if cur is None:
            break
        prev_t = pred.get(cur)
        if prev_t is None:
            break
        prev, kind, meta = prev_t
        if kind == "buy":
            gi, _ = cur
            node = nodes[gi]
            gals = float(meta["gallons"])
            price = float(meta["price"])
            purchases_rev.append(
                FuelPurchase(
                    mile_marker=node.mile,
                    latitude=node.latitude,
                    longitude=node.longitude,
                    station_name=node.name,
                    price_per_gallon=price,
                    gallons=gals,
                    cost_usd=round(gals * price, 2),
                )
            )
        cur = prev

    purchases_rev.reverse()
    total_gals = sum(p.gallons for p in purchases_rev)
    total_cost = round(sum(p.cost_usd for p in purchases_rev), 2)

    return OptimizeResult(
        total_cost_usd=total_cost,
        total_gallons_purchased=round(total_gals, 3),
        purchases=tuple(purchases_rev),
        nodes=tuple(nodes),
    )
