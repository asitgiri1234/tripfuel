from django.test import TestCase

from routing.services.optimize import (
    RouteNode,
    build_route_nodes,
    calculate_required_fuel,
    find_next_cheapest_station,
    get_reachable_stations,
    simulate_fuel_journey,
)

# Vehicle constants used throughout tests
MPG = 10.0
TANK_GALLONS = 50.0  # 500 miles max range


def _node(mile, price=None, kind="station", name="Station", lat=0.0, lon=0.0):
    """Helper to build a RouteNode for unit tests."""
    return RouteNode(
        mile=float(mile),
        latitude=lat,
        longitude=lon,
        price_per_gallon=float(price) if price is not None else None,
        name=name,
        kind=kind,
    )


class GetReachableStationsTests(TestCase):
    def test_reachable_ahead_only(self):
        nodes = (
            _node(0, kind="start", name="Start"),
            _node(100, 3.0, name="A"),
            _node(250, 3.5, name="B"),
            _node(600, 4.0, name="C"),
            _node(700, kind="end", name="End"),
        )
        # At start with full tank (50 gal * 10 mpg = 500 miles)
        reachable = get_reachable_stations(
            nodes, current_index=0, current_fuel_gallons=50.0, mpg=MPG
        )
        # A(100) and B(250) are within 500 miles; C(600) is not.
        self.assertEqual(reachable, [1, 2])

    def test_reachable_with_partial_fuel(self):
        nodes = (
            _node(0, kind="start", name="Start"),
            _node(100, 3.0, name="A"),
            _node(250, 3.5, name="B"),
            _node(400, 4.0, name="C"),
            _node(700, kind="end", name="End"),
        )
        # Only 15 gallons left (150 miles range)
        reachable = get_reachable_stations(
            nodes, current_index=0, current_fuel_gallons=15.0, mpg=MPG
        )
        # Only A(100) is within 150 miles; B(250) and C(400) are not.
        self.assertEqual(reachable, [1])

    def test_no_backtracking(self):
        nodes = (
            _node(0, kind="start", name="Start"),
            _node(100, 3.0, name="A"),
            _node(200, 3.5, name="B"),
            _node(700, kind="end", name="End"),
        )
        reachable = get_reachable_stations(
            nodes, current_index=2, current_fuel_gallons=50.0, mpg=MPG
        )
        # From B (mile 200), A at mile 100 is behind us.
        self.assertEqual(reachable, [])


class FindNextCheapestStationTests(TestCase):
    def test_finds_first_cheaper_and_cheapest(self):
        nodes = (
            _node(0, 4.0, name="Current"),
            _node(100, 3.9, name="A"),
            _node(250, 3.5, name="B"),
            _node(400, 4.2, name="C"),
        )
        first_cheaper, cheapest = find_next_cheapest_station(
            nodes, current_index=0, max_reach_miles=500, current_price=4.0
        )
        self.assertEqual(first_cheaper, 1)  # A at $3.90 is first cheaper
        self.assertEqual(cheapest, 2)  # B at $3.50 is absolute cheapest

    def test_no_cheaper_station(self):
        nodes = (
            _node(0, 3.0, name="Current"),
            _node(100, 3.5, name="A"),
            _node(250, 4.0, name="B"),
        )
        first_cheaper, cheapest = find_next_cheapest_station(
            nodes, current_index=0, max_reach_miles=500, current_price=3.0
        )
        self.assertIsNone(first_cheaper)
        self.assertEqual(cheapest, 1)  # A is cheapest among more expensive

    def test_beyond_reach_ignored(self):
        nodes = (
            _node(0, 4.0, name="Current"),
            _node(100, 3.0, name="A"),
            _node(600, 2.0, name="B"),  # beyond 500-mile window
        )
        first_cheaper, cheapest = find_next_cheapest_station(
            nodes, current_index=0, max_reach_miles=500, current_price=4.0
        )
        self.assertEqual(first_cheaper, 1)
        self.assertEqual(cheapest, 1)


class CalculateRequiredFuelTests(TestCase):
    def test_exact_amount(self):
        # Need to travel 100 miles at 10 mpg = 10 gallons, have 2 gallons
        need = calculate_required_fuel(
            current_fuel_gallons=2.0,
            distance_miles=100.0,
            mpg=MPG,
            tank_capacity_gallons=TANK_GALLONS,
        )
        self.assertEqual(need, 8.0)

    def test_already_sufficient(self):
        need = calculate_required_fuel(
            current_fuel_gallons=20.0,
            distance_miles=100.0,
            mpg=MPG,
            tank_capacity_gallons=TANK_GALLONS,
        )
        self.assertEqual(need, 0.0)

    def test_capped_by_tank(self):
        # Need 60 gallons for 600 miles, but tank only holds 50
        need = calculate_required_fuel(
            current_fuel_gallons=0.0,
            distance_miles=600.0,
            mpg=MPG,
            tank_capacity_gallons=TANK_GALLONS,
        )
        self.assertEqual(need, 50.0)


class SimulateFuelJourneyTests(TestCase):
    def test_short_route_no_stops_needed(self):
        """Route is 300 miles; vehicle range is 500. No purchases required."""
        nodes = (
            _node(0, kind="start", name="Start"),
            _node(300, kind="end", name="End"),
        )
        result = simulate_fuel_journey(
            nodes, tank_capacity_gallons=TANK_GALLONS, mpg=MPG
        )
        self.assertEqual(len(result.purchases), 0)
        self.assertEqual(result.total_cost_usd, 0.0)
        self.assertEqual(result.total_gallons_purchased, 0.0)

    def test_partial_fill_for_cheaper_station(self):
        """
        Start -> A(400,$4.00) -> B(600,$3.00) -> End(900).
        At A, a cheaper station B exists ahead, so we buy only enough for B.
        At B, no cheaper ahead and end is within range, so buy only enough for end.
        """
        nodes = (
            _node(0, kind="start", name="Start"),
            _node(400, 4.0, name="A"),
            _node(600, 3.0, name="B"),
            _node(900, kind="end", name="End"),
        )
        result = simulate_fuel_journey(
            nodes, tank_capacity_gallons=TANK_GALLONS, mpg=MPG
        )
        # Start -> A: travel 400 mi, use 40 gal, arrive with 10 gal.
        # At A: need 200 mi to B = 20 gal, have 10, buy 10 gal @ $4.00
        # A -> B: travel 200 mi, use 20 gal, arrive with 0 gal.
        # At B: need 300 mi to end = 30 gal, have 0, buy 30 gal @ $3.00
        self.assertEqual(len(result.purchases), 2)

        p_a = result.purchases[0]
        self.assertEqual(p_a.station_name, "A")
        self.assertEqual(p_a.gallons, 10.0)
        self.assertEqual(p_a.cost_usd, 40.0)
        self.assertEqual(p_a.reason, "partial_fill_for_cheaper_station")

        p_b = result.purchases[1]
        self.assertEqual(p_b.station_name, "B")
        self.assertEqual(p_b.gallons, 30.0)
        self.assertEqual(p_b.cost_usd, 90.0)
        self.assertEqual(p_b.reason, "partial_fill_for_end")

        self.assertEqual(result.total_gallons_purchased, 40.0)
        self.assertEqual(result.total_cost_usd, 130.0)

    def test_partial_fill_for_end(self):
        """
        Start -> A(400,$4.00) -> End(600).
        No station is cheaper than A ahead, and the end is within full-tank range,
        so at A we buy only enough to reach the end (not a full tank).
        """
        nodes = (
            _node(0, kind="start", name="Start"),
            _node(400, 4.0, name="A"),
            _node(600, kind="end", name="End"),
        )
        result = simulate_fuel_journey(
            nodes, tank_capacity_gallons=TANK_GALLONS, mpg=MPG
        )
        # Start -> A: 400 mi, use 40 gal, arrive with 10 gal.
        # At A: need 200 mi to end = 20 gal, have 10, buy 10 gal @ $4.00
        self.assertEqual(len(result.purchases), 1)
        p = result.purchases[0]
        self.assertEqual(p.station_name, "A")
        self.assertEqual(p.gallons, 10.0)
        self.assertEqual(p.cost_usd, 40.0)
        self.assertEqual(p.reason, "partial_fill_for_end")

    def test_full_fill_when_no_cheaper_ahead_and_end_out_of_range(self):
        """
        Start -> A(400,$4.00) -> B(800,$5.00) -> End(1000).
        At A, B is more expensive and end is beyond range, so we fill to full.
        At B, end is within range, so we buy only enough for end.
        """
        nodes = (
            _node(0, kind="start", name="Start"),
            _node(400, 4.0, name="A"),
            _node(800, 5.0, name="B"),
            _node(1000, kind="end", name="End"),
        )
        result = simulate_fuel_journey(
            nodes, tank_capacity_gallons=TANK_GALLONS, mpg=MPG
        )
        # Start -> A: 400 mi, use 40 gal, arrive with 10 gal.
        # At A: no cheaper ahead, end out of range. Fill full: buy 40 gal @ $4.00
        # A -> B: 400 mi, use 40 gal, arrive with 10 gal.
        # At B: end is 200 mi away, within range. Buy 10 gal @ $5.00
        self.assertEqual(len(result.purchases), 2)

        p_a = result.purchases[0]
        self.assertEqual(p_a.station_name, "A")
        self.assertEqual(p_a.gallons, 40.0)
        self.assertEqual(p_a.cost_usd, 160.0)
        self.assertEqual(p_a.reason, "full_fill_no_cheaper_ahead")

        p_b = result.purchases[1]
        self.assertEqual(p_b.station_name, "B")
        self.assertEqual(p_b.gallons, 10.0)
        self.assertEqual(p_b.cost_usd, 50.0)
        self.assertEqual(p_b.reason, "partial_fill_for_end")

        self.assertEqual(result.total_gallons_purchased, 50.0)
        self.assertEqual(result.total_cost_usd, 210.0)

    def test_unreachable_route_raises(self):
        """
        Start -> A(600,$4.00) -> End(1200).
        A is 600 miles away, beyond the 500-mile range. Should raise ValueError.
        """
        nodes = (
            _node(0, kind="start", name="Start"),
            _node(600, 4.0, name="A"),
            _node(1200, kind="end", name="End"),
        )
        with self.assertRaises(ValueError):
            simulate_fuel_journey(
                nodes, tank_capacity_gallons=TANK_GALLONS, mpg=MPG
            )

    def test_multiple_hops_varying_prices(self):
        """
        Start -> A(200,$4.00) -> B(450,$3.50) -> C(700,$2.50) -> End(1100).
        Greedy look-ahead should minimise cost by deferring purchases to C.
        """
        nodes = (
            _node(0, kind="start", name="Start"),
            _node(200, 4.0, name="A"),
            _node(450, 3.5, name="B"),
            _node(700, 2.5, name="C"),
            _node(1100, kind="end", name="End"),
        )
        result = simulate_fuel_journey(
            nodes, tank_capacity_gallons=TANK_GALLONS, mpg=MPG
        )
        # Start -> B: cheapest reachable from start is B at $3.50 (A is $4.00).
        # Travel 450 mi, use 45 gal, arrive with 5 gal.
        # At B: first cheaper is C at 700 ($2.50 < $3.50).
        # Need 250 mi = 25 gal, have 5, buy 20 gal @ $3.50.
        # B -> C: 250 mi, use 25 gal, arrive with 0 gal.
        # At C: no cheaper ahead. End is 400 mi away, within range.
        # Need 40 gal, have 0, buy 40 gal @ $2.50.
        self.assertEqual(len(result.purchases), 2)

        p_b = result.purchases[0]
        self.assertEqual(p_b.station_name, "B")
        self.assertEqual(p_b.gallons, 20.0)
        self.assertEqual(p_b.cost_usd, 70.0)
        self.assertEqual(p_b.reason, "partial_fill_for_cheaper_station")

        p_c = result.purchases[1]
        self.assertEqual(p_c.station_name, "C")
        self.assertEqual(p_c.gallons, 40.0)
        self.assertEqual(p_c.cost_usd, 100.0)
        self.assertEqual(p_c.reason, "partial_fill_for_end")

        self.assertEqual(result.total_gallons_purchased, 60.0)
        self.assertEqual(result.total_cost_usd, 170.0)


class BuildRouteNodesTests(TestCase):
    def test_filters_endpoints(self):
        """Stations very close to start or end should be dropped."""
        stations = [
            type("S", (), {"latitude": 0.0, "longitude": 0.0, "price_per_gallon": 3.0, "name": "NearStart", "mile_marker": 0.005})(),
            type("S", (), {"latitude": 0.0, "longitude": 0.0, "price_per_gallon": 3.5, "name": "Mid", "mile_marker": 50.0})(),
            type("S", (), {"latitude": 0.0, "longitude": 0.0, "price_per_gallon": 4.0, "name": "NearEnd", "mile_marker": 99.995})(),
        ]
        nodes = build_route_nodes(0.0, 0.0, 1.0, 1.0, 100.0, stations)
        kinds = [n.kind for n in nodes]
        names = [n.name for n in nodes]
        self.assertEqual(kinds, ["start", "station", "end"])
        self.assertEqual(names, ["Start", "Mid", "Finish"])
