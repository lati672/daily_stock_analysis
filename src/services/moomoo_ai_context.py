# -*- coding: utf-8 -*-
"""Build a compact, read-only Moomoo portfolio context for Agent Chat."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from src.brokers.futu.portfolio import FutuPortfolioError, FutuPositionSnapshot, load_futu_broker_snapshot


_VALID_MODES = frozenset({"position", "portfolio", "today_attribution"})


def _sum_optional(values: Iterable[Optional[float]]) -> Optional[float]:
    items = list(values)
    if not items or any(value is None for value in items):
        return None
    return sum(value or 0.0 for value in items)


def _analysis_code(code: str) -> str:
    normalized = str(code or "").strip().upper()
    if normalized.startswith("US."):
        return normalized[3:]
    if normalized.startswith("HK."):
        return f"HK{normalized[3:].zfill(5)}"
    if normalized.endswith(".HK"):
        return f"HK{normalized[:-3].zfill(5)}"
    return normalized.split(".", 1)[-1]


def _weighted_average(
    positions: Iterable[FutuPositionSnapshot],
    field: str,
) -> Optional[float]:
    usable = [position for position in positions if getattr(position, field) is not None and position.quantity]
    total_quantity = sum(abs(position.quantity) for position in usable)
    if total_quantity <= 0:
        return None
    return sum(float(getattr(position, field)) * abs(position.quantity) for position in usable) / total_quantity


def _group_positions(positions: Iterable[FutuPositionSnapshot]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], List[FutuPositionSnapshot]] = {}
    for position in positions:
        key = (_analysis_code(position.code), (position.currency or "").upper())
        grouped.setdefault(key, []).append(position)

    compact: List[Dict[str, Any]] = []
    for (code, currency), items in grouped.items():
        quantity = sum(item.quantity for item in items)
        market_value = _sum_optional(item.market_value for item in items)
        holding_pnl = _sum_optional(item.holding_pnl for item in items)
        today_pnl = _sum_optional(item.today_pnl for item in items)
        unrealized_pnl = _sum_optional(item.unrealized_pnl for item in items)
        realized_pnl = _sum_optional(item.realized_pnl for item in items)
        cost_basis = None
        if market_value is not None and holding_pnl is not None:
            cost_basis = market_value - holding_pnl
        compact.append(
            {
                "code": code,
                "name": next((item.name for item in items if item.name), ""),
                "currency": currency,
                "quantity": quantity,
                "average_cost": _weighted_average(items, "cost_price"),
                "current_price": _weighted_average(items, "current_price"),
                "market_value": market_value,
                "holding_pnl": holding_pnl,
                "holding_pnl_pct": holding_pnl / cost_basis * 100 if holding_pnl is not None and cost_basis and cost_basis > 0 else None,
                "today_pnl": today_pnl,
                "today_change_pct": _weighted_average(items, "today_change_pct"),
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": _weighted_average(items, "unrealized_pnl_pct"),
                "realized_pnl": realized_pnl,
            }
        )
    return compact


def _build_market_context(market: str, positions: List[Dict[str, Any]], mode: str) -> Dict[str, Any]:
    total_market_value = _sum_optional(position["market_value"] for position in positions)
    total_today_pnl = _sum_optional(position["today_pnl"] for position in positions)
    total_holding_pnl = _sum_optional(position["holding_pnl"] for position in positions)
    for position in positions:
        value = position["market_value"]
        position["weight_pct"] = value / total_market_value * 100 if value is not None and total_market_value and total_market_value > 0 else None
        today_pnl = position["today_pnl"]
        position["today_pnl_contribution_pct"] = (
            today_pnl / total_today_pnl * 100
            if today_pnl is not None and total_today_pnl is not None and abs(total_today_pnl) > 1e-9
            else None
        )
    sort_field = "today_pnl" if mode == "today_attribution" else "market_value"
    positions.sort(key=lambda item: abs(item.get(sort_field) or 0), reverse=True)
    return {
        "market": market,
        "currency": positions[0]["currency"] if positions else ("HKD" if market == "HK" else "USD"),
        "total_market_value": total_market_value,
        "total_holding_pnl": total_holding_pnl,
        "total_today_pnl": total_today_pnl,
        "positions": positions[:30],
    }


def enrich_moomoo_chat_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve opt-in Moomoo data and remove transport-only flags.

    The returned LLM context intentionally excludes account ids, OpenD connection
    details, security-firm metadata, and any trading capability.
    """

    enriched = dict(context)
    include_portfolio = enriched.pop("include_moomoo_portfolio", False) is True
    requested_mode = str(enriched.pop("moomoo_context_mode", "portfolio"))
    if not include_portfolio:
        return enriched
    mode = requested_mode if requested_mode in _VALID_MODES else "portfolio"

    try:
        snapshot = load_futu_broker_snapshot()
    except FutuPortfolioError as exc:
        enriched["moomoo_portfolio_context"] = {
            "status": "unavailable",
            "mode": mode,
            "read_only": True,
            "message": str(exc),
        }
        return enriched

    positions = _group_positions(snapshot.positions)
    if mode == "position":
        selected_code = _analysis_code(str(enriched.get("stock_code") or ""))
        positions = [position for position in positions if position["code"] == selected_code]

    markets: List[Dict[str, Any]] = []
    for market in ("US", "HK", "OTHER"):
        market_positions = [
            position for position in positions
            if ("HK" if position["code"].startswith("HK") else "US" if position["currency"] == "USD" else "OTHER") == market
        ]
        if market_positions:
            markets.append(_build_market_context(market, market_positions, mode))

    enriched["moomoo_portfolio_context"] = {
        "status": "ok",
        "mode": mode,
        "read_only": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "calculation_note": "Weights and today's P/L attribution are deterministic values calculated before the LLM call.",
        "markets": markets,
    }
    return enriched
