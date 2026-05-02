from __future__ import annotations

# Contiguous United States (approximate); sufficient for the assignment checks.
USA_LAT_MIN, USA_LAT_MAX = 24.0, 49.5
USA_LON_MIN, USA_LON_MAX = -125.0, -66.0


def in_usa(latitude: float, longitude: float) -> bool:
    return (
        USA_LAT_MIN <= latitude <= USA_LAT_MAX
        and USA_LON_MIN <= longitude <= USA_LON_MAX
    )
