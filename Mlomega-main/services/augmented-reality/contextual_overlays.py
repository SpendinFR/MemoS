from __future__ import annotations

"""Bounded, opt-in contextual overlays for the augmented-reality service.

No class in this module opens memory.db or calls an LLM.  Weather is fetched only
after the wearer enables the feature and provides an accuracy-bounded location.
The sky catalogue is calculated locally from public JPL approximate elements and
a small, explicit bright-star catalogue.
"""

import hashlib
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
JPL_APPROXIMATE_ELEMENTS_SOURCE = (
    "https://ssd.jpl.nasa.gov/planets/approx_pos.html"
)
LEGI_DATASET_SEARCH_ENDPOINT = "https://datasets-server.huggingface.co/search"
LEGI_DATASET_ID = "AgentPublic/legi"
LEGI_DATASET_SOURCE = (
    "https://www.data.gouv.fr/datasets/"
    "legi-codes-lois-et-reglements-consolides-vectorises"
)


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _location(payload: dict[str, Any]) -> tuple[float, float, float]:
    latitude = _finite(payload.get("latitude"))
    longitude = _finite(payload.get("longitude"))
    accuracy = _finite(payload.get("horizontal_accuracy_m"))
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise ValueError("invalid WGS84 location")
    if accuracy <= 0.0 or accuracy > 50.0:
        raise ValueError("location accuracy is not qualified")
    return latitude, longitude, accuracy


def _bounded_text(value: Any, limit: int = 180) -> str:
    clean = " ".join(str(value or "").split())
    return clean[:limit]


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:18]


class OpenMeteoWeatherProvider:
    """Current-weather client with a durable 15-minute location-cell cache."""

    def __init__(
        self,
        *,
        cache_path: str | Path | None = None,
        opener: Any | None = None,
        ttl_s: float = 900.0,
        endpoint: str = OPEN_METEO_ENDPOINT,
    ) -> None:
        default_cache = (
            Path(__file__).resolve().parents[2]
            / "storage"
            / "runtime"
            / "weather-cache-v1.json"
        )
        self.cache_path = Path(
            cache_path
            or os.environ.get("MLOMEGA_WEATHER_CACHE_PATH")
            or default_cache
        )
        self.opener = opener or urllib.request.urlopen
        self.ttl_s = max(600.0, min(float(ttl_s), 1800.0))
        self.endpoint = str(endpoint).rstrip("?")
        self._cache = self._load_cache()

    @property
    def available(self) -> bool:
        return self.endpoint == OPEN_METEO_ENDPOINT

    def current(self, payload: dict[str, Any]) -> dict[str, Any]:
        latitude, longitude, accuracy = _location(payload)
        key = f"{latitude:.2f},{longitude:.2f}"
        cached = self._cache.get(key)
        now = time.time()
        if cached and now - float(cached.get("fetched_at_unix", 0.0)) <= self.ttl_s:
            return {**cached, "cache_state": "fresh", "location_accuracy_m": accuracy}

        query = urllib.parse.urlencode(
            {
                "latitude": f"{latitude:.6f}",
                "longitude": f"{longitude:.6f}",
                "current": (
                    "temperature_2m,apparent_temperature,precipitation,"
                    "weather_code,wind_speed_10m"
                ),
                "timezone": "auto",
                "forecast_days": "1",
            }
        )
        try:
            with self.opener(f"{self.endpoint}?{query}", timeout=3.0) as response:
                raw = response.read(128_001)
            if len(raw) > 128_000:
                raise ValueError("Open-Meteo response too large")
            decoded = json.loads(raw.decode("utf-8"))
            current = decoded.get("current")
            units = decoded.get("current_units")
            if not isinstance(current, dict) or not isinstance(units, dict):
                raise ValueError("Open-Meteo current weather is missing")
            record = {
                "provider": "open-meteo",
                "source": self.endpoint,
                "cell": key,
                "latitude": _finite(decoded.get("latitude", latitude)),
                "longitude": _finite(decoded.get("longitude", longitude)),
                "timezone": _bounded_text(decoded.get("timezone"), 80),
                "observed_at": _bounded_text(current.get("time"), 64),
                "temperature_c": _finite(current.get("temperature_2m")),
                "apparent_temperature_c": _finite(
                    current.get("apparent_temperature")
                ),
                "precipitation_mm": _finite(current.get("precipitation")),
                "weather_code": int(current.get("weather_code")),
                "wind_speed_kmh": _finite(current.get("wind_speed_10m")),
                "fetched_at_unix": now,
                "fetched_at_utc": datetime.fromtimestamp(
                    now, timezone.utc
                ).isoformat(),
                "cache_state": "network",
                "location_accuracy_m": accuracy,
            }
            self._cache[key] = record
            self._save_cache()
            return record
        except Exception:
            if not cached:
                raise
            return {
                **cached,
                "cache_state": "stale",
                "location_accuracy_m": accuracy,
            }

    def card(self, payload: dict[str, Any]) -> dict[str, Any]:
        weather = self.current(payload)
        stale = weather["cache_state"] == "stale"
        condition = weather_code_label(int(weather["weather_code"]))
        observed = weather.get("observed_at") or weather.get("fetched_at_utc")
        suffix = f" · mesure {observed}"
        if stale:
            suffix = f" · dernière mesure disponible {observed} (réseau indisponible)"
        text = (
            f"{weather['temperature_c']:.1f} °C, ressenti "
            f"{weather['apparent_temperature_c']:.1f} °C · {condition} · "
            f"vent {weather['wind_speed_kmh']:.0f} km/h{suffix}"
        )
        return {
            "type": "ui_intent",
            "contracts_version": "v19.0",
            "ui_intent_id": (
                "ar-weather-"
                + _stable_id(payload.get("session_id"), weather["cell"])
            ),
            "producer": "ultralive",
            "component": "context_card",
            "anchor": {"type": "head_locked", "side": "upper_right"},
            "content": {
                "kind": "weather_context",
                "title": "MÉTÉO // " + condition.upper(),
                "text": text,
                "source": weather["source"],
                "observed_at": observed,
                "stale": stale,
                "location_accuracy_m": weather["location_accuracy_m"],
            },
            "truth_level": "remembered" if stale else "observed",
            "confidence": 0.72 if stale else 0.92,
            "priority": 0.22,
            "ttl_ms": 45_000,
            "ui_hint": {"dismissible": True},
            "evidence_refs": [
                weather["source"],
                f"geo:{weather['cell']}",
                f"weather-observed:{observed}",
            ],
        }

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        try:
            decoded = json.loads(self.cache_path.read_text(encoding="utf-8"))
            rows = decoded.get("cells") if isinstance(decoded, dict) else None
            if isinstance(rows, dict):
                return {
                    str(key): dict(value)
                    for key, value in rows.items()
                    if isinstance(value, dict)
                }
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.cache_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(
                {"schema_version": 1, "cells": self._cache},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(temp, self.cache_path)


def weather_code_label(code: int) -> str:
    if code == 0:
        return "ciel clair"
    if code in {1, 2, 3}:
        return "nuageux"
    if code in {45, 48}:
        return "brouillard"
    if code in {51, 53, 55, 56, 57}:
        return "bruine"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "pluie"
    if code in {71, 73, 75, 77, 85, 86}:
        return "neige"
    if code in {95, 96, 99}:
        return "orage"
    return "conditions variables"


@dataclass(frozen=True)
class _Orbit:
    name: str
    a: tuple[float, float]
    e: tuple[float, float]
    inc: tuple[float, float]
    longitude: tuple[float, float]
    perihelion: tuple[float, float]
    node: tuple[float, float]


# JPL table 1, valid 1800–2050.  Earth is retained internally as EM Bary.
_ORBITS = (
    _Orbit("Mercure", (0.38709927, 0.00000037), (0.20563593, 0.00001906), (7.00497902, -0.00594749), (252.25032350, 149472.67411175), (77.45779628, 0.16047689), (48.33076593, -0.12534081)),
    _Orbit("Vénus", (0.72333566, 0.00000390), (0.00677672, -0.00004107), (3.39467605, -0.00078890), (181.97909950, 58517.81538729), (131.60246718, 0.00268329), (76.67984255, -0.27769418)),
    _Orbit("Terre", (1.00000261, 0.00000562), (0.01671123, -0.00004392), (-0.00001531, -0.01294668), (100.46457166, 35999.37244981), (102.93768193, 0.32327364), (0.0, 0.0)),
    _Orbit("Mars", (1.52371034, 0.00001847), (0.09339410, 0.00007882), (1.84969142, -0.00813131), (-4.55343205, 19140.30268499), (-23.94362959, 0.44441088), (49.55953891, -0.29257343)),
    _Orbit("Jupiter", (5.20288700, -0.00011607), (0.04838624, -0.00013253), (1.30439695, -0.00183714), (34.39644051, 3034.74612775), (14.72847983, 0.21252668), (100.47390909, 0.20469106)),
    _Orbit("Saturne", (9.53667594, -0.00125060), (0.05386179, -0.00050991), (2.48599187, 0.00193609), (49.95424423, 1222.49362201), (92.59887831, -0.41897216), (113.66242448, -0.28867794)),
    _Orbit("Uranus", (19.18916464, -0.00196176), (0.04725744, -0.00004397), (0.77263783, -0.00242939), (313.23810451, 428.48202785), (170.95427630, 0.40805281), (74.01692503, 0.04240589)),
    _Orbit("Neptune", (30.06992276, 0.00026291), (0.00859048, 0.00005105), (1.77004347, 0.00035372), (-55.12002969, 218.45945325), (44.96476227, -0.32241464), (131.78422574, -0.00508664)),
)


_STARS = (
    ("Sirius", 6.75248, -16.7161, "Grand Chien"),
    ("Canopus", 6.39920, -52.6957, "Carène"),
    ("Arcturus", 14.2610, 19.1824, "Bouvier"),
    ("Vega", 18.6156, 38.7837, "Lyre"),
    ("Capella", 5.27815, 45.9980, "Cocher"),
    ("Rigel", 5.24230, -8.2016, "Orion"),
    ("Procyon", 7.65503, 5.2250, "Petit Chien"),
    ("Betelgeuse", 5.91953, 7.4071, "Orion"),
    ("Altair", 19.8464, 8.8683, "Aigle"),
    ("Aldebaran", 4.59868, 16.5093, "Taureau"),
    ("Antares", 16.4901, -26.4320, "Scorpion"),
    ("Spica", 13.4199, -11.1614, "Vierge"),
    ("Pollux", 7.75526, 28.0262, "Gémeaux"),
    ("Fomalhaut", 22.9608, -29.6222, "Poisson austral"),
    ("Deneb", 20.6905, 45.2803, "Cygne"),
    ("Bellatrix", 5.41885, 6.3497, "Orion"),
    ("Saiph", 5.79594, -9.6696, "Orion"),
    ("Alnitak", 5.67931, -1.9426, "Orion"),
    ("Alnilam", 5.60356, -1.2019, "Orion"),
    ("Mintaka", 5.53344, -0.2991, "Orion"),
)

_CONSTELLATION_EDGES = (
    ("Betelgeuse", "Bellatrix"),
    ("Betelgeuse", "Alnitak"),
    ("Bellatrix", "Mintaka"),
    ("Alnitak", "Alnilam"),
    ("Alnilam", "Mintaka"),
    ("Alnitak", "Saiph"),
    ("Mintaka", "Rigel"),
    ("Saiph", "Rigel"),
)


class LocalPlanetariumProvider:
    """Build a bounded sky-dome contract without network or model inference."""

    @property
    def available(self) -> bool:
        return True

    def dome(self, payload: dict[str, Any]) -> dict[str, Any]:
        latitude, longitude, accuracy = _location(payload)
        north_yaw = _finite(payload.get("world_north_yaw_deg"))
        heading_accuracy = _finite(payload.get("heading_accuracy_deg"))
        if payload.get("north_calibrated") is not True:
            raise ValueError("world north is not calibrated")
        if heading_accuracy < 0.0 or heading_accuracy > 30.0:
            raise ValueError("heading accuracy is not qualified")
        tracking = payload.get("tracking_position")
        if not isinstance(tracking, dict):
            raise ValueError("tracking position is missing")
        origin = {
            axis: _finite(tracking.get(axis))
            for axis in ("x", "y", "z")
        }
        captured = _parse_time(payload.get("captured_at_utc"))
        julian = _julian_day(captured)

        bodies: list[dict[str, Any]] = []
        earth = _heliocentric(_ORBITS[2], julian)
        sun_ra, sun_dec = _vector_to_ra_dec(tuple(-item for item in earth))
        bodies.append(
            _sky_body(
                "Soleil",
                "sun",
                sun_ra,
                sun_dec,
                latitude,
                longitude,
                julian,
                None,
            )
        )
        for orbit in _ORBITS:
            if orbit.name == "Terre":
                continue
            planet = _heliocentric(orbit, julian)
            geo = tuple(planet[index] - earth[index] for index in range(3))
            ra, dec = _vector_to_ra_dec(geo)
            bodies.append(
                _sky_body(
                    orbit.name,
                    "planet",
                    ra,
                    dec,
                    latitude,
                    longitude,
                    julian,
                    None,
                )
            )
        for name, ra_hours, dec_deg, constellation in _STARS:
            bodies.append(
                _sky_body(
                    name,
                    "star",
                    ra_hours * 15.0,
                    dec_deg,
                    latitude,
                    longitude,
                    julian,
                    constellation,
                )
            )

        # Keep the contract small while still showing bodies just below the horizon.
        visible = [body for body in bodies if body["altitude_deg"] >= -12.0]
        names = {body["name"] for body in visible}
        edges = [
            {"from": start, "to": end, "constellation": "Orion"}
            for start, end in _CONSTELLATION_EDGES
            if start in names and end in names
        ]
        return {
            "type": "ui_intent",
            "contracts_version": "v19.0",
            "ui_intent_id": "ar-sky-" + _stable_id(
                payload.get("session_id"), captured.strftime("%Y-%m-%dT%H:%M")
            ),
            "producer": "ultralive",
            "component": "sky_dome",
            "anchor": {
                "coordinate_space": "tracking_local",
                "position": origin,
            },
            "content": {
                "kind": "planetarium",
                "bodies": visible[:32],
                "constellation_edges": edges,
                "world_north_yaw_deg": north_yaw,
                "calibration_id": _bounded_text(
                    payload.get("calibration_id"), 120
                ),
                "captured_at_utc": captured.isoformat(),
                "location_accuracy_m": accuracy,
                "heading_accuracy_deg": heading_accuracy,
                "method": "jpl_approx_1800_2050_plus_bright_stars",
                "memory_write": False,
            },
            "truth_level": "inferred",
            "confidence": 0.82,
            "priority": 0.20,
            "ttl_ms": 180_000,
            "ui_hint": {"dismissible": True},
            "evidence_refs": [
                JPL_APPROXIMATE_ELEMENTS_SOURCE,
                f"geo:{latitude:.4f},{longitude:.4f}",
                f"time:{captured.isoformat()}",
                "heading:android-compass",
            ],
        }


def _parse_time(raw: Any) -> datetime:
    text = str(raw or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _julian_day(value: datetime) -> float:
    return value.timestamp() / 86400.0 + 2440587.5


def _heliocentric(orbit: _Orbit, julian: float) -> tuple[float, float, float]:
    centuries = (julian - 2451545.0) / 36525.0
    a = orbit.a[0] + orbit.a[1] * centuries
    e = orbit.e[0] + orbit.e[1] * centuries
    inc = math.radians(orbit.inc[0] + orbit.inc[1] * centuries)
    longitude = orbit.longitude[0] + orbit.longitude[1] * centuries
    perihelion = orbit.perihelion[0] + orbit.perihelion[1] * centuries
    node = orbit.node[0] + orbit.node[1] * centuries
    mean_anomaly = math.radians((longitude - perihelion) % 360.0)
    eccentric = mean_anomaly
    for _ in range(12):
        delta = (
            eccentric - e * math.sin(eccentric) - mean_anomaly
        ) / (1.0 - e * math.cos(eccentric))
        eccentric -= delta
        if abs(delta) < 1e-12:
            break
    x_prime = a * (math.cos(eccentric) - e)
    y_prime = a * math.sqrt(1.0 - e * e) * math.sin(eccentric)
    omega = math.radians(perihelion - node)
    omega_node = math.radians(node)
    cos_w, sin_w = math.cos(omega), math.sin(omega)
    cos_o, sin_o = math.cos(omega_node), math.sin(omega_node)
    cos_i, sin_i = math.cos(inc), math.sin(inc)
    x = (
        (cos_w * cos_o - sin_w * sin_o * cos_i) * x_prime
        + (-sin_w * cos_o - cos_w * sin_o * cos_i) * y_prime
    )
    y = (
        (cos_w * sin_o + sin_w * cos_o * cos_i) * x_prime
        + (-sin_w * sin_o + cos_w * cos_o * cos_i) * y_prime
    )
    z = sin_w * sin_i * x_prime + cos_w * sin_i * y_prime
    return x, y, z


def _vector_to_ra_dec(vector: tuple[float, float, float]) -> tuple[float, float]:
    x, y_ecliptic, z_ecliptic = vector
    obliquity = math.radians(23.43928)
    y = math.cos(obliquity) * y_ecliptic - math.sin(obliquity) * z_ecliptic
    z = math.sin(obliquity) * y_ecliptic + math.cos(obliquity) * z_ecliptic
    ra = math.degrees(math.atan2(y, x)) % 360.0
    dec = math.degrees(math.atan2(z, math.hypot(x, y)))
    return ra, dec


def _sky_body(
    name: str,
    kind: str,
    ra_deg: float,
    dec_deg: float,
    latitude: float,
    longitude: float,
    julian: float,
    constellation: str | None,
) -> dict[str, Any]:
    gmst = (
        280.46061837
        + 360.98564736629 * (julian - 2451545.0)
        + 0.000387933 * ((julian - 2451545.0) / 36525.0) ** 2
    ) % 360.0
    hour_angle = math.radians((gmst + longitude - ra_deg) % 360.0)
    lat = math.radians(latitude)
    dec = math.radians(dec_deg)
    altitude = math.asin(
        math.sin(lat) * math.sin(dec)
        + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)
    )
    azimuth = math.atan2(
        -math.sin(hour_angle) * math.cos(dec),
        math.sin(dec) * math.cos(lat)
        - math.cos(dec) * math.sin(lat) * math.cos(hour_angle),
    )
    return {
        "name": name,
        "kind": kind,
        "constellation": constellation,
        "azimuth_deg": round(math.degrees(azimuth) % 360.0, 3),
        "altitude_deg": round(math.degrees(altitude), 3),
    }


class FrenchLegalCorpusProvider:
    """Global France legal lookup over the public, consolidated LEGI corpus.

    The provider searches the national corpus as a whole; no scenario, offence
    or article list is hard-coded.  Only rows explicitly marked in force and
    valid on the lookup date may reach the glasses.  A local Kiwix provider can
    be supplied as a network-independent fallback.
    """

    _STOPWORDS = {
        "afin", "alors", "avec", "avoir", "aux", "cela", "cette", "comme",
        "dans", "depuis", "des", "donc", "elle", "elles", "est", "être",
        "fait", "faire", "ils", "les", "leur", "lors", "mais", "mes", "moi",
        "nous", "notre", "par", "pas", "pour", "pouvez", "que", "quel",
        "quelle", "qui", "quoi", "sans", "ses", "son", "sous", "sur", "tout",
        "une", "vos", "vous", "votre",
    }

    def __init__(
        self,
        *,
        opener: Any | None = None,
        fallback: Any | None = None,
        endpoint: str = LEGI_DATASET_SEARCH_ENDPOINT,
        cache_ttl_s: float = 900.0,
    ) -> None:
        self.opener = opener or urllib.request.urlopen
        self.fallback = fallback
        self.endpoint = str(endpoint)
        self.cache_ttl_s = max(60.0, min(float(cache_ttl_s), 3600.0))
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def available(self) -> bool:
        return self.endpoint.startswith("https://datasets-server.huggingface.co/")

    def lookup(self, topic: str) -> dict[str, Any]:
        query = self._search_query(topic)
        cached = self._cache.get(query)
        now = time.time()
        if cached and now - cached[0] <= self.cache_ttl_s:
            return {**cached[1], "cache_state": "fresh"}
        try:
            params = urllib.parse.urlencode(
                {
                    "dataset": LEGI_DATASET_ID,
                    "config": "latest",
                    "split": "train",
                    "query": query,
                }
            )
            with self.opener(f"{self.endpoint}?{params}", timeout=2.5) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("LEGI search response too large")
            decoded = json.loads(raw.decode("utf-8"))
            result = self._select_current_row(decoded, query=query)
            self._cache[query] = (now, result)
            return {**result, "cache_state": "network"}
        except Exception:
            if self.fallback is not None and bool(
                getattr(self.fallback, "available", False)
            ):
                fallback = dict(self.fallback.lookup(query))
                return {
                    **fallback,
                    "provider": "local-kiwix",
                    "dataset_source": LEGI_DATASET_SOURCE,
                    "cache_state": "fallback",
                }
            if cached:
                return {**cached[1], "cache_state": "stale"}
            raise

    def _search_query(self, topic: str) -> str:
        words = re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ'-]+", _bounded_text(topic, 600))
        selected = [
            word
            for word in words
            if len(word) >= 3 and word.casefold() not in self._STOPWORDS
        ]
        query = " ".join(selected[-18:]).strip()
        if len(query) < 3:
            raise ValueError("legal lookup query is too vague")
        return query[:320]

    def _select_current_row(
        self,
        decoded: Any,
        *,
        query: str,
    ) -> dict[str, Any]:
        rows = decoded.get("rows") if isinstance(decoded, dict) else None
        if not isinstance(rows, list):
            raise LookupError("LEGI search returned no rows")
        today = datetime.now(timezone.utc).date().isoformat()
        query_terms = {
            token.casefold()
            for token in re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ'-]+", query)
            if len(token) >= 3
        }
        candidates: list[tuple[float, dict[str, Any]]] = []
        for rank, item in enumerate(rows[:40]):
            row = item.get("row") if isinstance(item, dict) else None
            if not isinstance(row, dict):
                continue
            status = str(
                row.get("status") or row.get("etat") or ""
            ).strip().upper()
            if status not in {"VIGUEUR", "VIGUEUR_DIFF"}:
                continue
            start = str(
                row.get("start") or row.get("date_debut") or ""
            ).strip()[:10]
            end = str(
                row.get("end") or row.get("date_fin") or ""
            ).strip()[:10]
            if start and start > today:
                continue
            if end and end not in {"2999-01-01", "9999-12-31"} and end < today:
                continue
            summary = _bounded_text(
                row.get("chunk_text") or row.get("text") or "", 720
            )
            if len(summary) < 30:
                continue
            title = _bounded_text(
                row.get("title") or row.get("titre") or "Texte LEGI", 180
            )
            searchable = f"{title} {summary}".casefold()
            matched = sorted(term for term in query_terms if term in searchable)
            if not matched:
                continue
            coverage = len(matched) / max(1, min(len(query_terms), 8))
            relevance = min(1.0, coverage + max(0.0, 0.12 - rank * 0.006))
            doc_id = _bounded_text(
                row.get("doc_id") or row.get("id") or "", 80
            )
            source = (
                "https://www.legifrance.gouv.fr/codes/article_lc/" + doc_id
                if doc_id.startswith("LEGIARTI")
                else LEGI_DATASET_SOURCE
            )
            candidates.append((relevance, {
                "provider": "legi-global-search",
                "title": title,
                "summary": summary,
                "source": source,
                "dataset_source": LEGI_DATASET_SOURCE,
                "doc_id": doc_id,
                "status": status,
                "start_date": start,
                "end_date": end,
                "matched_terms": matched,
                "relevance": round(relevance, 3),
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            }))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates or candidates[0][0] < 0.20:
            raise LookupError("LEGI results are not relevant enough")
        best = dict(candidates[0][1])
        best["alternatives"] = [
            {
                "title": candidate["title"],
                "source": candidate["source"],
                "doc_id": candidate["doc_id"],
                "status": candidate["status"],
                "relevance": candidate["relevance"],
            }
            for _, candidate in candidates[1:3]
        ]
        return best
