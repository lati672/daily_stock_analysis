# -*- coding: utf-8 -*-
"""Independent daily scheduler for the Moomoo portfolio digest."""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional
from zoneinfo import ZoneInfo

from src.config import Config, get_config
from src.core.trading_calendar import is_market_open
from src.utils.sanitize import sanitize_diagnostic_text

logger = logging.getLogger(__name__)
DEFAULT_MOOMOO_DAILY_REPORT_TIME = "18:10"


def normalize_daily_report_time(value: Any) -> str:
    candidate = str(value or "").strip()
    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", candidate):
        return candidate
    return DEFAULT_MOOMOO_DAILY_REPORT_TIME


def is_us_market_trading_day(now: datetime) -> bool:
    """Return whether the US market's local calendar date is a trading day."""
    aware_now = now.astimezone() if now.tzinfo is None else now
    us_date = aware_now.astimezone(ZoneInfo("America/New_York")).date()
    return is_market_open("us", us_date)


def next_daily_report_run(
    now: datetime,
    schedule_time: str,
    *,
    eligible_day: Optional[Callable[[datetime], bool]] = None,
) -> datetime:
    normalized = normalize_daily_report_time(schedule_time)
    hour, minute = (int(part) for part in normalized.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    for _ in range(370):
        if eligible_day is None or eligible_day(target):
            break
        target += timedelta(days=1)
    return target


class MoomooDailyReportScheduler:
    """Run one digest daily without enabling the main analysis scheduler."""

    def __init__(
        self,
        *,
        config_provider: Callable[[], Config] = get_config,
        report_runner: Optional[Callable[[Config], Dict[str, Any]]] = None,
        now_provider: Callable[[], datetime] = datetime.now,
        us_trading_day_checker: Callable[[datetime], bool] = is_us_market_trading_day,
    ) -> None:
        self._config_provider = config_provider
        self._report_runner = report_runner
        self._now_provider = now_provider
        self._us_trading_day_checker = us_trading_day_checker
        self._condition = threading.Condition()
        self._run_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._shutdown = False
        self._enabled = False
        self._schedule_time = DEFAULT_MOOMOO_DAILY_REPORT_TIME
        self._next_run_at: Optional[str] = None
        self._last_run_at: Optional[str] = None
        self._last_success_at: Optional[str] = None
        self._last_error: Optional[str] = None

    def _run_report(self) -> Dict[str, Any]:
        config = self._config_provider()
        if self._report_runner is not None:
            return self._report_runner(config)
        from src.services.moomoo_daily_report_service import MoomooDailyReportService

        return MoomooDailyReportService(config).generate_and_send()

    def _run_once(
        self,
        *,
        lock_held: bool = False,
        respect_us_calendar: bool = False,
    ) -> bool:
        if not lock_held and not self._run_lock.acquire(blocking=False):
            return False
        now = self._now_provider()
        try:
            if respect_us_calendar and not self._us_trading_day_checker(now):
                logger.info("Skip Moomoo daily portfolio report: US market is closed")
                return True
            self._last_run_at = now.isoformat()
            self._run_report()
            self._last_success_at = self._now_provider().isoformat()
            self._last_error = None
            return True
        except Exception as exc:  # noqa: BLE001 - scheduled failure must not stop WebUI.
            self._last_error = sanitize_diagnostic_text(exc)
            logger.exception("Moomoo daily portfolio report failed: %s", self._last_error)
            return False
        finally:
            self._run_lock.release()

    def _loop(self) -> None:
        while True:
            with self._condition:
                if self._shutdown:
                    return
                if not self._enabled:
                    self._next_run_at = None
                    self._condition.wait()
                    continue
                now = self._now_provider()
                target = next_daily_report_run(
                    now,
                    self._schedule_time,
                    eligible_day=self._us_trading_day_checker,
                )
                self._next_run_at = target.isoformat()
                wait_seconds = max(0.0, (target - now).total_seconds())
                notified = self._condition.wait(timeout=wait_seconds)
                if self._shutdown:
                    return
                if notified or not self._enabled:
                    continue
            self._run_once(respect_us_calendar=True)

    def reconcile_from_config(self) -> None:
        config = self._config_provider()
        enabled = bool(getattr(config, "moomoo_daily_report_enabled", False))
        schedule_time = normalize_daily_report_time(
            getattr(config, "moomoo_daily_report_time", DEFAULT_MOOMOO_DAILY_REPORT_TIME)
        )
        with self._condition:
            self._enabled = enabled
            self._schedule_time = schedule_time
            self._shutdown = False
            if not enabled:
                self._next_run_at = None
            if enabled and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(
                    target=self._loop,
                    daemon=True,
                    name="moomoo-daily-report-scheduler",
                )
                self._thread.start()
            self._condition.notify_all()

    def run_now(self) -> Dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            return {"accepted": False, "running": True, "reason": "report_already_running"}
        worker = threading.Thread(
            target=lambda: self._run_once(lock_held=True),
            daemon=True,
            name="moomoo-daily-report-manual",
        )
        try:
            worker.start()
        except Exception:
            self._run_lock.release()
            raise
        return {"accepted": True, "running": True}

    def stop(self) -> None:
        with self._condition:
            self._enabled = False
            self._shutdown = True
            self._next_run_at = None
            self._condition.notify_all()
            thread = self._thread
            self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def status(self) -> Dict[str, Any]:
        with self._condition:
            return {
                "enabled": self._enabled,
                "us_market_open_today": self._us_trading_day_checker(self._now_provider()),
                "schedule_time": self._schedule_time,
                "next_run_at": self._next_run_at,
                "running": self._run_lock.locked(),
                "last_run_at": self._last_run_at,
                "last_success_at": self._last_success_at,
                "last_error": self._last_error,
            }
