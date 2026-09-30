"""Tests for the scheduled read-only Moomoo portfolio digest."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.services.moomoo_daily_report_scheduler import (
    MoomooDailyReportScheduler,
    is_us_market_trading_day,
    next_daily_report_run,
    normalize_daily_report_time,
)
from src.services.moomoo_daily_report_service import (
    MoomooDailyReportError,
    MoomooDailyReportService,
)


def _portfolio_context():
    return {
        "status": "ok",
        "read_only": True,
        "markets": [{
            "market": "US",
            "currency": "USD",
            "total_market_value": 1000.0,
            "total_today_pnl": 25.0,
            "positions": [{
                "code": "AAPL",
                "name": "Apple",
                "weight_pct": 100.0,
                "today_pnl": 25.0,
            }],
        }],
    }


def test_daily_report_service_uses_sanitized_portfolio_context_and_agent() -> None:
    executor = MagicMock()
    executor.chat.return_value = SimpleNamespace(
        success=True,
        content="## Daily digest\n\nAAPL contributed most.",
        provider="openai",
        model="test-model",
        error=None,
    )
    with patch(
        "src.services.moomoo_daily_report_service.enrich_moomoo_chat_context",
        return_value={"moomoo_portfolio_context": _portfolio_context()},
    ), patch(
        "src.agent.factory.build_agent_chat_executor",
        return_value=executor,
    ):
        result = MoomooDailyReportService(SimpleNamespace(report_language="zh")).generate()

    assert result["content"].startswith("## Daily digest")
    assert result["position_count"] == 1
    context = executor.chat.call_args.kwargs["context"]["moomoo_portfolio_context"]
    assert context["read_only"] is True
    assert "account_id" not in str(context)
    prompt = executor.chat.call_args.args[0]
    assert "search_stock_news" in prompt
    assert "AAPL" in prompt


def test_daily_report_service_fails_before_llm_when_opend_is_unavailable() -> None:
    with patch(
        "src.services.moomoo_daily_report_service.enrich_moomoo_chat_context",
        return_value={"moomoo_portfolio_context": {"status": "unavailable", "message": "OpenD offline"}},
    ), patch("src.agent.factory.build_agent_chat_executor") as build_executor:
        with pytest.raises(MoomooDailyReportError, match="OpenD offline"):
            MoomooDailyReportService(SimpleNamespace(report_language="zh")).generate()
    build_executor.assert_not_called()


def test_generate_and_send_targets_discord_only() -> None:
    notification = MagicMock()
    notification.send_to_discord.return_value = True
    service = MoomooDailyReportService(SimpleNamespace(report_language="zh"))
    with patch.object(
        service,
        "generate",
        return_value={"content": "日报正文", "provider": "openai", "model": "model", "position_count": 2},
    ), patch("src.notification.NotificationService", return_value=notification):
        result = service.generate_and_send()

    assert result["sent"] is True
    sent = notification.send_to_discord.call_args.args[0]
    assert "Moomoo 持仓日报" in sent
    assert "日报正文" in sent
    assert not hasattr(notification, "send") or not notification.send.called


def test_daily_report_time_normalization_and_next_run() -> None:
    assert normalize_daily_report_time("08:15") == "08:15"
    assert normalize_daily_report_time("25:00") == "18:10"
    now = datetime(2026, 9, 3, 18, 11)
    assert next_daily_report_run(now, "18:10") == datetime(2026, 9, 4, 18, 10)
    assert next_daily_report_run(now, "19:00") == datetime(2026, 9, 3, 19, 0)
    friday = datetime(2026, 9, 4, 19, 0, tzinfo=ZoneInfo("Australia/Sydney"))
    assert next_daily_report_run(
        friday,
        "18:10",
        eligible_day=is_us_market_trading_day,
    ) == datetime(2026, 9, 8, 18, 10, tzinfo=ZoneInfo("Australia/Sydney"))


def test_scheduled_report_skips_us_market_holiday_but_manual_run_still_works() -> None:
    completed = threading.Event()
    calls = []

    def runner(config):
        calls.append(config)
        completed.set()
        return {"sent": True}

    scheduler = MoomooDailyReportScheduler(
        config_provider=lambda: SimpleNamespace(),
        report_runner=runner,
        us_trading_day_checker=lambda _now: False,
    )
    try:
        assert scheduler._run_once(respect_us_calendar=True) is True
        assert calls == []
        assert scheduler.status()["last_run_at"] is None
        assert scheduler.status()["us_market_open_today"] is False

        assert scheduler.run_now()["accepted"] is True
        assert completed.wait(1)
        assert len(calls) == 1
    finally:
        scheduler.stop()


def test_scheduler_reconciles_toggle_and_runs_manual_report_once() -> None:
    config = SimpleNamespace(moomoo_daily_report_enabled=True, moomoo_daily_report_time="18:10")
    completed = threading.Event()
    calls = []

    def runner(received_config):
        calls.append(received_config)
        completed.set()
        return {"sent": True}

    scheduler = MoomooDailyReportScheduler(
        config_provider=lambda: config,
        report_runner=runner,
    )
    try:
        scheduler.reconcile_from_config()
        deadline = time.time() + 1
        while scheduler.status()["next_run_at"] is None and time.time() < deadline:
            time.sleep(0.01)
        assert scheduler.status()["enabled"] is True
        assert scheduler.status()["schedule_time"] == "18:10"
        assert scheduler.status()["next_run_at"] is not None

        assert scheduler.run_now()["accepted"] is True
        assert completed.wait(1)
        deadline = time.time() + 1
        while scheduler.status()["running"] and time.time() < deadline:
            time.sleep(0.01)
        assert calls == [config]
        assert scheduler.status()["last_success_at"] is not None

        config.moomoo_daily_report_enabled = False
        scheduler.reconcile_from_config()
        assert scheduler.status()["enabled"] is False
        assert scheduler.status()["next_run_at"] is None
    finally:
        scheduler.stop()
