"""API contract tests for the Moomoo daily portfolio digest controls."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_moomoo_daily_report_scheduler, get_system_config_service


class _FakeScheduler:
    def __init__(self) -> None:
        self.enabled = False
        self.run_requests = 0

    def status(self):
        return {
            "enabled": self.enabled,
            "us_market_open_today": True,
            "schedule_time": "18:10",
            "next_run_at": "2026-09-04T18:10:00" if self.enabled else None,
            "running": False,
            "last_run_at": None,
            "last_success_at": None,
            "last_error": None,
        }

    def run_now(self):
        self.run_requests += 1
        return {"accepted": True, "running": True}


class _FakeConfigService:
    def __init__(self, scheduler: _FakeScheduler) -> None:
        self.scheduler = scheduler
        self.items = []

    def get_config(self, include_schema=False):
        return {"config_version": "version-1"}

    def update(self, *, config_version, items, reload_now):
        assert config_version == "version-1"
        assert reload_now is True
        self.items = items
        self.scheduler.enabled = items[0]["value"] == "true"
        return {"success": True}


def test_moomoo_daily_report_status_toggle_and_manual_run(tmp_path) -> None:
    scheduler = _FakeScheduler()
    config_service = _FakeConfigService(scheduler)
    app = create_app(static_dir=tmp_path / "static")
    app.dependency_overrides[get_moomoo_daily_report_scheduler] = lambda: scheduler
    app.dependency_overrides[get_system_config_service] = lambda: config_service

    with TestClient(app) as client:
        status = client.get("/api/v1/portfolio/brokers/moomoo/daily-report/status")
        assert status.status_code == 200
        assert status.json()["enabled"] is False

        updated = client.put(
            "/api/v1/portfolio/brokers/moomoo/daily-report/settings",
            json={"enabled": True},
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is True
        assert config_service.items == [{
            "key": "MOOMOO_DAILY_REPORT_ENABLED",
            "value": "true",
        }]

        run = client.post("/api/v1/portfolio/brokers/moomoo/daily-report/run")
        assert run.status_code == 200
        assert run.json() == {"accepted": True, "running": True, "reason": None}
        assert scheduler.run_requests == 1
