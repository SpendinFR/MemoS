from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


route_provider = _load("route_provider_t0", "services/live-pc/route_provider.py")
sessionhub = _load("sessionhub_route_t0", "services/live-pc/sessionhub.py")
sessionhub_http = _load("sessionhub_http_route_t0", "services/live-pc/sessionhub_http.py")

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return self._payload


def test_osrm_geometry_is_bounded_and_keeps_lat_lon_order(monkeypatch):
    payload = {
        "code": "Ok",
        "routes": [
            {
                "distance": 321.4,
                "duration": 120.0,
                "geometry": {
                    "coordinates": [
                        [2.3522, 48.8566],
                        [2.3523, 48.8567],
                        [2.3530, 48.8570],
                    ]
                },
            }
        ],
    }
    monkeypatch.setattr(
        route_provider.urllib.request,
        "urlopen",
        lambda request, timeout: _Response(payload),
    )
    result = route_provider.RouteProvider(
        base_url="https://router.example", profile="walking"
    ).resolve(
        origin_latitude=48.8566,
        origin_longitude=2.3522,
        destination_latitude=48.8570,
        destination_longitude=2.3530,
    )
    assert result["distance_m"] == 321.4
    assert result["points"][0] == [48.8566, 2.3522]
    assert result["points"][-1] == [48.857, 2.353]
    assert result["point_count"] >= 2


def test_route_provider_refuses_invalid_or_unbounded_coordinates():
    provider = route_provider.RouteProvider(base_url="https://router.example")
    with pytest.raises(route_provider.RouteProviderError, match="invalid"):
        provider.resolve(
            origin_latitude=200,
            origin_longitude=2,
            destination_latitude=48,
            destination_longitude=2,
        )
    with pytest.raises(route_provider.RouteProviderError, match="200 km"):
        provider.resolve(
            origin_latitude=48,
            origin_longitude=2,
            destination_latitude=43,
            destination_longitude=2,
        )


class _InjectedRoute:
    def __init__(self):
        self.calls = []

    def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "schema_version": 1,
            "provider": "injected",
            "profile": "walking",
            "distance_m": 10,
            "duration_s": 8,
            "points": [[48.0, 2.0], [48.0001, 2.0001]],
            "point_count": 2,
        }


def test_navigation_route_is_token_gated_and_uses_injected_provider():
    hub = sessionhub.SessionHub()
    resolver = _InjectedRoute()
    app = sessionhub_http.create_app(
        hub,
        enable_signaling=False,
        route_provider=resolver,
    )
    with TestClient(app) as client:
        created = client.post(
            "/session/create", json={"device_id": "xreal-test"}
        ).json()
        body = {
            "session_id": created["session_id"],
            "token": created["token"],
            "origin_latitude": 48.0,
            "origin_longitude": 2.0,
            "destination_latitude": 48.0001,
            "destination_longitude": 2.0001,
        }
        response = client.post("/navigation/route", json=body)
        assert response.status_code == 200
        assert response.json()["provider"] == "injected"
        assert len(resolver.calls) == 1

        body["token"] = "wrong"
        assert client.post("/navigation/route", json=body).status_code == 401
