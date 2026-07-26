from __future__ import annotations

"""Small, bounded OSRM-compatible route provider for XREAL world navigation.

No request is made at startup or while FreeGuy is disabled.  The provider only
returns map geometry; the glasses remain responsible for GPS/XREAL calibration
and for rendering the route in tracking-local metres.
"""

import json
import math
import os
import urllib.parse
import urllib.request
from typing import Any


MAX_RESPONSE_BYTES = 2_000_000
MAX_ROUTE_POINTS = 512


class RouteProviderError(RuntimeError):
    pass


class RouteProvider:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        profile: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get(
                "MLOMEGA_ROUTE_BASE_URL", "https://router.project-osrm.org"
            )
        ).rstrip("/")
        self.profile = (
            profile or os.environ.get("MLOMEGA_ROUTE_PROFILE", "driving")
        ).strip()
        self.timeout_s = max(
            1.0,
            min(
                float(
                    timeout_s
                    if timeout_s is not None
                    else os.environ.get("MLOMEGA_ROUTE_TIMEOUT_S", "10")
                ),
                25.0,
            ),
        )
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MLOMEGA_ROUTE_BASE_URL must be an HTTP(S) endpoint")
        if not self.profile or not all(
            char.isalnum() or char in {"_", "-"} for char in self.profile
        ):
            raise ValueError("MLOMEGA_ROUTE_PROFILE is invalid")

    def resolve(
        self,
        *,
        origin_latitude: float,
        origin_longitude: float,
        destination_latitude: float,
        destination_longitude: float,
    ) -> dict[str, Any]:
        origin = _coordinate(origin_latitude, origin_longitude, "origin")
        destination = _coordinate(
            destination_latitude, destination_longitude, "destination"
        )
        direct_m = _haversine_m(*origin, *destination)
        if direct_m < 1.0:
            raise RouteProviderError("origin and destination are indistinguishable")
        if direct_m > 200_000.0:
            raise RouteProviderError("route exceeds the 200 km product bound")

        coordinates = (
            f"{origin[1]:.7f},{origin[0]:.7f};"
            f"{destination[1]:.7f},{destination[0]:.7f}"
        )
        query = urllib.parse.urlencode(
            {
                "overview": "full",
                "geometries": "geojson",
                "steps": "false",
                "alternatives": "false",
            }
        )
        url = (
            f"{self.base_url}/route/v1/"
            f"{urllib.parse.quote(self.profile, safe='')}/{coordinates}?{query}"
        )
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "MLOmega-XREAL-Route/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except OSError as exc:
            raise RouteProviderError(
                f"route service unavailable: {type(exc).__name__}"
            ) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RouteProviderError("route response exceeds size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RouteProviderError("route service returned invalid JSON") from exc
        routes = payload.get("routes") if isinstance(payload, dict) else None
        if payload.get("code") != "Ok" or not isinstance(routes, list) or not routes:
            message = str(payload.get("message") or payload.get("code") or "no route")
            raise RouteProviderError(message[:180])
        route = routes[0]
        geometry = route.get("geometry") if isinstance(route, dict) else None
        raw_points = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(raw_points, list) or len(raw_points) < 2:
            raise RouteProviderError("route geometry is missing")

        points: list[list[float]] = []
        for item in raw_points:
            if not isinstance(item, list) or len(item) < 2:
                raise RouteProviderError("route geometry contains an invalid point")
            longitude = float(item[0])
            latitude = float(item[1])
            _coordinate(latitude, longitude, "route")
            points.append([latitude, longitude])
        points = _bounded_points(points)
        distance_m = float(route.get("distance") or 0.0)
        duration_s = float(route.get("duration") or 0.0)
        if not math.isfinite(distance_m) or distance_m <= 0.0:
            raise RouteProviderError("route distance is invalid")
        if not math.isfinite(duration_s) or duration_s < 0.0:
            duration_s = 0.0
        return {
            "schema_version": 1,
            "provider": urllib.parse.urlparse(self.base_url).hostname,
            "profile": self.profile,
            "distance_m": round(distance_m, 2),
            "duration_s": round(duration_s, 2),
            "points": points,
            "point_count": len(points),
        }


def _coordinate(latitude: float, longitude: float, name: str) -> tuple[float, float]:
    latitude = float(latitude)
    longitude = float(longitude)
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or latitude < -90.0
        or latitude > 90.0
        or longitude < -180.0
        or longitude > 180.0
    ):
        raise RouteProviderError(f"{name} coordinate is invalid")
    return latitude, longitude


def _bounded_points(points: list[list[float]]) -> list[list[float]]:
    # Remove sub-metre jitter first.  If a long route still exceeds the UI bound,
    # uniformly retain endpoints and intermediate geometry.  The glasses later
    # render only the nearby slice (<=128 points).
    filtered = [points[0]]
    for point in points[1:-1]:
        if _haversine_m(*filtered[-1], *point) >= 1.0:
            filtered.append(point)
    filtered.append(points[-1])
    if len(filtered) <= MAX_ROUTE_POINTS:
        return filtered
    result: list[list[float]] = []
    last = len(filtered) - 1
    for index in range(MAX_ROUTE_POINTS):
        source = round(index * last / (MAX_ROUTE_POINTS - 1))
        point = filtered[source]
        if not result or point != result[-1]:
            result.append(point)
    if result[-1] != filtered[-1]:
        result[-1] = filtered[-1]
    return result


def _haversine_m(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(delta_lambda / 2.0) ** 2
    )
    return radius * 2.0 * math.atan2(math.sqrt(value), math.sqrt(1.0 - value))
