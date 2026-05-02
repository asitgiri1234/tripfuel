from __future__ import annotations

from rest_framework import serializers

from routing.validators import in_usa


class TripFuelRequestSerializer(serializers.Serializer):
    start_latitude = serializers.FloatField(required=False)
    start_longitude = serializers.FloatField(required=False)
    end_latitude = serializers.FloatField(required=False)
    end_longitude = serializers.FloatField(required=False)

    start_address = serializers.CharField(required=False, allow_blank=False)
    end_address = serializers.CharField(required=False, allow_blank=False)

    max_off_route_miles = serializers.FloatField(required=False, default=15.0, min_value=1.0, max_value=40.0)

    def validate(self, attrs):
        if attrs.get("start_address") is not None:
            attrs["start_address"] = str(attrs["start_address"]).strip()
        if attrs.get("end_address") is not None:
            attrs["end_address"] = str(attrs["end_address"]).strip()

        has_coords = all(
            k in attrs and attrs[k] is not None
            for k in ("start_latitude", "start_longitude", "end_latitude", "end_longitude")
        )
        has_addr = bool(attrs.get("start_address")) and bool(attrs.get("end_address"))
        if has_coords == has_addr:
            raise serializers.ValidationError(
                "Provide either (start_latitude, start_longitude, end_latitude, end_longitude) "
                "or (start_address, end_address), not both and not neither."
            )
        if has_coords:
            for lab in (
                ("start_latitude", "start_longitude"),
                ("end_latitude", "end_longitude"),
            ):
                lat, lon = attrs[lab[0]], attrs[lab[1]]
                if not in_usa(lat, lon):
                    raise serializers.ValidationError(f"{lab[0]}/{lab[1]} must be within the USA.")
        return attrs
