# -*- coding: utf-8 -*-
"""Read real stock holdings from a Futu OpenD instance."""

from __future__ import annotations

import ipaddress
import logging
import math
import os
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional

from data_provider.us_index_mapping import is_us_stock_code
from src.services.stock_code_utils import normalize_code


logger = logging.getLogger(__name__)


class FutuPortfolioError(RuntimeError):
    """Raised when a Futu portfolio cannot be resolved safely."""


@dataclass(frozen=True)
class _FutuAccount:
    """Identify one usable real Futu securities account."""

    acc_id: int
    security_firm: Any
    role: str


@dataclass(frozen=True)
class _FutuApi:
    """Hold the imported Futu SDK surface used by portfolio loading."""

    OpenQuoteContext: Any
    OpenSecTradeContext: Any
    Market: Any
    RET_OK: Any
    SecurityFirm: Any
    SecurityType: Any
    TrdEnv: Any
    TrdMarket: Any
    Currency: Any = None


@dataclass(frozen=True)
class FutuAccountSnapshot:
    """Low-cardinality account metadata safe for the private Web workspace."""

    account_id: int
    role: str
    security_firm: str
    position_count: int
    currency: str
    market_value: Optional[float]
    holding_pnl: Optional[float]
    holding_pnl_pct: Optional[float]
    total_pnl: Optional[float]
    total_pnl_pct: Optional[float]
    today_pnl: Optional[float]
    today_pnl_pct: Optional[float]


@dataclass(frozen=True)
class FutuCashBalanceSnapshot:
    """One native-currency cash balance returned by ``accinfo_query``."""

    account_id: int
    currency: str
    cash: float
    available_for_withdrawal: Optional[float]
    net_cash_power: Optional[float]


@dataclass(frozen=True)
class FutuPositionSnapshot:
    """One read-only position returned by Futu OpenD."""

    account_id: int
    code: str
    name: str
    position_side: str
    quantity: float
    available_quantity: Optional[float]
    cost_price: Optional[float]
    current_price: Optional[float]
    market_value: Optional[float]
    holding_pnl: Optional[float]
    holding_pnl_pct: Optional[float]
    unrealized_pnl: Optional[float]
    unrealized_pnl_pct: Optional[float]
    realized_pnl: Optional[float]
    today_pnl: Optional[float]
    today_change_pct: Optional[float]
    currency: str
    exchange_rate_to_reporting_currency: Optional[float] = None


@dataclass(frozen=True)
class FutuBrokerSnapshot:
    """Read-only broker snapshot used by the Web account page."""

    host: str
    port: int
    currency: str
    total_market_value: Optional[float]
    holding_pnl: Optional[float]
    holding_pnl_pct: Optional[float]
    total_pnl: Optional[float]
    total_pnl_pct: Optional[float]
    today_pnl: Optional[float]
    today_pnl_pct: Optional[float]
    accounts: List[FutuAccountSnapshot]
    positions: List[FutuPositionSnapshot]
    cash_balances: List[FutuCashBalanceSnapshot] = field(default_factory=list)


_SUPPORTED_ACCOUNT_ROLES = frozenset({"NORMAL", "MASTER"})
_SUPPORTED_ANALYSIS_MARKETS = frozenset({"US", "HK", "SH", "SZ"})
_UNKNOWN_SECURITY_TYPES = frozenset({"", "N/A", "NONE", "UNKNOWN", "NAN"})
_STATIC_INFO_BATCH_SIZE = 100
_MARKET_SNAPSHOT_BATCH_SIZE = 100
_CASH_FIELD_MAP = {
    "AUD": ("au_cash", "au_avl_withdrawal_cash", "aud_net_cash_power"),
    "USD": ("us_cash", "us_avl_withdrawal_cash", "usd_net_cash_power"),
    "HKD": ("hk_cash", "hk_avl_withdrawal_cash", "hkd_net_cash_power"),
}


def _extract_cash_balances(account_id: int, info: Dict[str, Any]) -> List[FutuCashBalanceSnapshot]:
    """Extract native-currency balances without converting or combining them."""
    balances: List[FutuCashBalanceSnapshot] = []
    for currency, (cash_field, withdrawal_field, power_field) in _CASH_FIELD_MAP.items():
        cash = _optional_finite_float(info.get(cash_field))
        if cash is None:
            continue
        balances.append(FutuCashBalanceSnapshot(
            account_id=account_id,
            currency=currency,
            cash=cash,
            available_for_withdrawal=_optional_finite_float(info.get(withdrawal_field)),
            net_cash_power=_optional_finite_float(info.get(power_field)),
        ))
    return balances


def _load_futu_api() -> _FutuApi:
    """Import the Moomoo/Futu-compatible SDK surface or raise an actionable error."""

    try:
        from moomoo import (
            Currency,
            Market,
            OpenQuoteContext,
            OpenSecTradeContext,
            RET_OK,
            SecurityFirm,
            SecurityType,
            TrdEnv,
            TrdMarket,
        )
    except ImportError:
        try:
            from futu import (
                Currency,
                Market,
                OpenQuoteContext,
                OpenSecTradeContext,
                RET_OK,
                SecurityFirm,
                SecurityType,
                TrdEnv,
                TrdMarket,
            )
        except ImportError as exc:
            raise FutuPortfolioError(
                "未安装 Futu OpenAPI SDK；请安装 `moomoo-api`，或执行 "
                "`pip install \"futu-api==10.9.6908\"`。"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - SDK import initializes logging
            raise FutuPortfolioError(f"加载 Futu OpenAPI SDK 失败: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - SDK import initializes its file logger
        raise FutuPortfolioError(f"加载 Futu OpenAPI SDK 失败: {exc}") from exc

    return _FutuApi(
        OpenQuoteContext=OpenQuoteContext,
        OpenSecTradeContext=OpenSecTradeContext,
        Market=Market,
        RET_OK=RET_OK,
        SecurityFirm=SecurityFirm,
        SecurityType=SecurityType,
        TrdEnv=TrdEnv,
        TrdMarket=TrdMarket,
        Currency=Currency,
    )


def _enum_text(value: Any) -> str:
    """Normalize SDK enum-like values for stable comparisons."""

    if value is None:
        return ""
    name = getattr(value, "name", None)
    return str(name if name is not None else value).strip().upper()


def _iter_rows(data: Any, operation: str) -> Iterable[Any]:
    """Iterate the pandas-style table returned by the pinned Futu SDK."""

    iterrows = getattr(data, "iterrows", None)
    if not callable(iterrows):
        raise FutuPortfolioError(f"{operation}返回了非表格数据")
    return (row for _, row in iterrows())


def _safe_close(context: Any) -> None:
    """Close an SDK context without masking the primary operation result."""

    if context is None:
        return
    try:
        context.close()
    except Exception:  # pragma: no cover - closing is best effort
        logger.debug("关闭 Futu OpenD 连接失败", exc_info=True)


def _optional_finite_float(value: Any) -> Optional[float]:
    """Convert an SDK cell to a JSON-safe float, preserving unavailable values."""

    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _sum_complete(values: Iterable[Optional[float]]) -> Optional[float]:
    """Sum values only when the source returned every component."""

    items = list(values)
    return sum(items) if items and all(item is not None for item in items) else None


def _pnl_percentage(pnl: Optional[float], current_value: Optional[float]) -> Optional[float]:
    """Return P/L relative to the value before that P/L, when meaningful."""

    if pnl is None or current_value is None:
        return None
    basis = current_value - pnl
    if not math.isfinite(basis) or basis <= 0:
        return None
    return pnl / basis * 100


def _infer_position_fx_rates(
    positions: Iterable[FutuPositionSnapshot],
    *,
    reporting_currency: str,
    reporting_market_value: Optional[float],
) -> Dict[str, float]:
    """Infer one foreign-currency rate from OpenD's converted market value.

    OpenD returns each position in its native currency while ``accinfo_query``
    returns the account market value in the requested reporting currency.  When
    there is exactly one foreign currency, the difference uniquely determines
    the conversion rate and keeps P/L aligned with the account valuation.
    """

    items = list(positions)
    rates = {reporting_currency: 1.0}
    if reporting_market_value is None or not items:
        return rates
    if any(item.market_value is None for item in items):
        return rates
    foreign_currencies = {
        item.currency for item in items if item.currency != reporting_currency
    }
    if len(foreign_currencies) != 1:
        return rates
    foreign_currency = next(iter(foreign_currencies))
    reporting_value = sum(
        item.market_value or 0.0
        for item in items
        if item.currency == reporting_currency
    )
    foreign_value = sum(
        item.market_value or 0.0
        for item in items
        if item.currency == foreign_currency
    )
    converted_foreign_value = reporting_market_value - reporting_value
    if foreign_value <= 0 or converted_foreign_value <= 0:
        return rates
    rate = converted_foreign_value / foreign_value
    if math.isfinite(rate) and rate > 0:
        rates[foreign_currency] = rate
    return rates


def _sum_converted_position_field(
    positions: Iterable[FutuPositionSnapshot],
    *,
    field: str,
    rates: Dict[str, float],
) -> Optional[float]:
    """Sum one complete position field after converting to reporting currency."""

    converted: List[Optional[float]] = []
    for position in positions:
        value = getattr(position, field)
        rate = rates.get(position.currency)
        converted.append(value * rate if value is not None and rate is not None else None)
    return _sum_complete(converted)


def _load_today_change_percentages(
    api: _FutuApi,
    host: str,
    port: int,
    positions: Iterable[FutuPositionSnapshot],
) -> Dict[str, float]:
    """Load price changes for the same session as each position's nominal price."""

    current_prices = {
        position.code: position.current_price
        for position in positions
        if position.code
    }
    unique_codes = list(current_prices)
    if not unique_codes:
        return {}

    context = None
    changes: Dict[str, float] = {}
    try:
        context = api.OpenQuoteContext(host=host, port=port)
        for offset in range(0, len(unique_codes), _MARKET_SNAPSHOT_BATCH_SIZE):
            batch = unique_codes[offset:offset + _MARKET_SNAPSHOT_BATCH_SIZE]
            ret, data = context.get_market_snapshot(batch)
            if ret != api.RET_OK:
                logger.warning("查询 Futu 今日涨幅失败: %s", data)
                continue
            for row in _iter_rows(data, "Futu 行情快照查询"):
                code = str(row.get("code", "") or "").strip().upper()
                last_price = _optional_finite_float(row.get("last_price"))
                previous_close = _optional_finite_float(row.get("prev_close_price"))
                if not code or last_price is None or previous_close is None or previous_close <= 0:
                    continue

                candidates = [
                    (last_price, (last_price - previous_close) / previous_close * 100)
                ]
                for prefix in ("pre", "after"):
                    extended_price = _optional_finite_float(row.get(f"{prefix}_price"))
                    if extended_price is None or extended_price <= 0:
                        continue
                    extended_change = _optional_finite_float(
                        row.get(f"{prefix}_change_rate")
                    )
                    if extended_change is None:
                        extended_change = (
                            (extended_price - last_price) / last_price * 100
                            if last_price > 0
                            else None
                        )
                    if extended_change is not None:
                        candidates.append((extended_price, extended_change))

                current_price = current_prices.get(code)
                if current_price is None:
                    changes[code] = candidates[0][1]
                    continue

                # ``nominal_price`` follows the active quote session. Select the
                # regular/pre-market/after-hours snapshot whose price is closest
                # to it so the displayed percentage and P/L share one baseline.
                _, changes[code] = min(
                    candidates,
                    key=lambda candidate: abs(candidate[0] - current_price),
                )
    except Exception:  # noqa: BLE001 - quotes are optional enrichment
        logger.warning("查询 Futu 今日涨幅失败，持仓将继续加载", exc_info=True)
    finally:
        _safe_close(context)
    return changes


def _connection_settings() -> tuple[str, int]:
    """Return the validated IPv4 OpenD host and port from environment settings."""

    host = (os.getenv("FUTU_OPEND_HOST") or "127.0.0.1").strip()
    raw_port = (os.getenv("FUTU_OPEND_PORT") or "11111").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise FutuPortfolioError(f"FUTU_OPEND_PORT 不是有效端口: {raw_port!r}") from exc
    if not host or not 1 <= port <= 65535:
        raise FutuPortfolioError(f"Futu OpenD 地址无效: {host!r}:{port}")

    address_text = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        address = ipaddress.ip_address(address_text)
    except ValueError:
        address = None
    if address is not None and address.version != 4:
        raise FutuPortfolioError(
            "当前 Futu 集成的网络层仅支持 IPv4；"
            f"FUTU_OPEND_HOST 当前为 {host!r}，请改用 IPv4 地址或可解析到 IPv4 的主机名。"
        )
    return host, port


def _configured_account_id() -> Optional[int]:
    """Return the optional configured real account ID."""

    value = (os.getenv("FUTU_ACC_ID") or "").strip()
    if not value:
        return None
    try:
        account_id = int(value)
    except ValueError as exc:
        raise FutuPortfolioError("FUTU_ACC_ID 必须是正整数账户 ID") from exc
    if account_id <= 0:
        raise FutuPortfolioError("FUTU_ACC_ID 必须是正整数账户 ID")
    return account_id


def _configured_security_firm(api: _FutuApi) -> Any:
    """Resolve one firm, defaulting to the SDK's official auto-detection mode."""

    name = (os.getenv("FUTU_SECURITY_FIRM") or "NONE").strip().upper()
    firm = getattr(api.SecurityFirm, name, None)
    if firm is None:
        raise FutuPortfolioError(f"不支持的 FUTU_SECURITY_FIRM: {name}")
    return firm


def _discover_real_accounts(api: _FutuApi, host: str, port: int) -> List[_FutuAccount]:
    """Discover explicitly ACTIVE NORMAL or MASTER REAL accounts."""

    accounts: List[_FutuAccount] = []
    seen_ids = set()
    requested_acc_id = _configured_account_id()
    security_firm = _configured_security_firm(api)
    context = None
    try:
        context = api.OpenSecTradeContext(
            host=host,
            port=port,
            filter_trdmarket=api.TrdMarket.NONE,
            security_firm=security_firm,
        )
        ret, data = context.get_acc_list()
        if ret != api.RET_OK:
            raise FutuPortfolioError(f"查询 Futu 真实账户失败: {data}")
        for row in _iter_rows(data, "Futu 账户查询"):
            if _enum_text(row.get("trd_env")) != "REAL":
                continue
            if _enum_text(row.get("acc_status")) != "ACTIVE":
                continue
            if _enum_text(row.get("acc_role")) not in _SUPPORTED_ACCOUNT_ROLES:
                continue
            raw_acc_id = row.get("acc_id")
            try:
                acc_id = int(raw_acc_id)
                exact_integer = isinstance(raw_acc_id, str) or bool(
                    raw_acc_id == acc_id
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise FutuPortfolioError(
                    "Futu 账户查询返回了无效账户 ID"
                ) from exc
            if isinstance(raw_acc_id, bool) or not exact_integer or acc_id <= 0:
                raise FutuPortfolioError("Futu 账户查询返回了无效账户 ID")
            if acc_id in seen_ids:
                continue
            returned_firm_name = _enum_text(row.get("security_firm"))
            returned_firm = getattr(
                api.SecurityFirm,
                returned_firm_name,
                security_firm,
            )
            seen_ids.add(acc_id)
            accounts.append(_FutuAccount(
                acc_id=acc_id,
                security_firm=returned_firm,
                role=_enum_text(row.get("acc_role")),
            ))
    except FutuPortfolioError:
        raise
    except Exception as exc:  # noqa: BLE001 - translate SDK/network failures
        raise FutuPortfolioError(f"查询 Futu 真实账户失败: {exc}") from exc
    finally:
        _safe_close(context)

    if requested_acc_id is not None:
        accounts = [account for account in accounts if account.acc_id == requested_acc_id]
        if not accounts:
            raise FutuPortfolioError(
                "FUTU_ACC_ID 未匹配到可用的真实证券账户；请检查账户 ID、券商和 OpenD 登录状态。"
            )

    if not accounts:
        raise FutuPortfolioError(
            "未找到状态为 ACTIVE 的 Futu REAL 普通或 MASTER 证券账户"
        )
    return accounts


def _load_position_codes(
    api: _FutuApi,
    host: str,
    port: int,
    accounts: Iterable[_FutuAccount],
) -> List[str]:
    """Load deduplicated non-zero LONG position codes from selected accounts."""

    codes: List[str] = []
    seen_codes = set()
    skipped_short_count = 0
    skipped_unknown_side_count = 0

    for account in accounts:
        context = None
        try:
            context = api.OpenSecTradeContext(
                host=host,
                port=port,
                filter_trdmarket=api.TrdMarket.NONE,
                security_firm=account.security_firm,
            )
            ret, data = context.position_list_query(
                trd_env=api.TrdEnv.REAL,
                acc_id=account.acc_id,
                refresh_cache=True,
            )
            if ret != api.RET_OK:
                raise FutuPortfolioError(f"查询 Futu 真实持仓失败: {data}")
            for row in _iter_rows(data, "Futu 持仓查询"):
                position_side = _enum_text(row.get("position_side"))
                if position_side == "SHORT":
                    skipped_short_count += 1
                    continue
                if position_side != "LONG":
                    skipped_unknown_side_count += 1
                    continue
                raw_code = row.get("code")
                code = (
                    raw_code.strip().upper()
                    if isinstance(raw_code, str)
                    else ""
                )
                raw_quantity = row.get("qty")
                try:
                    if isinstance(raw_quantity, bool):
                        raise TypeError("boolean quantity")
                    quantity = float(raw_quantity)
                except (TypeError, ValueError) as exc:
                    suffix = f": {code}" if code else ""
                    raise FutuPortfolioError(f"Futu 持仓数量无效{suffix}") from exc
                if not math.isfinite(quantity):
                    suffix = f": {code}" if code else ""
                    raise FutuPortfolioError(f"Futu 持仓数量无效{suffix}")
                if quantity == 0:
                    continue
                if not isinstance(raw_code, str):
                    raise FutuPortfolioError("Futu 非零持仓返回了无效证券代码")
                if not code:
                    raise FutuPortfolioError("Futu 非零持仓返回了空证券代码")
                market, separator, symbol = code.partition(".")
                if not separator or not market or not symbol:
                    raise FutuPortfolioError(
                        f"Futu 非零持仓返回了无效证券代码: {code}"
                    )
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                codes.append(code)
        except FutuPortfolioError:
            raise
        except Exception as exc:  # noqa: BLE001 - translate SDK/network errors for CLI callers
            raise FutuPortfolioError(f"查询 Futu 真实持仓失败: {exc}") from exc
        finally:
            _safe_close(context)

    if skipped_short_count:
        logger.info("已跳过 %d 个 Futu SHORT 空头持仓", skipped_short_count)
    if skipped_unknown_side_count:
        logger.warning(
            "已跳过 %d 个持仓方向不是 LONG 的 Futu 持仓",
            skipped_unknown_side_count,
        )
    return codes


def _market_prefix(code: str) -> str:
    """Extract the Futu market prefix from a qualified security code."""

    return code.split(".", 1)[0] if "." in code else ""


def _is_cn_b_share_code(code: str) -> bool:
    """Return whether a qualified Futu code is a Shanghai/Shenzhen B-share."""

    prefix, separator, symbol = code.partition(".")
    if not separator or not (symbol.isdigit() and len(symbol) == 6):
        return False
    return (prefix == "SH" and symbol.startswith("900")) or (
        prefix == "SZ" and symbol.startswith("200")
    )


def _to_analysis_code(futu_code: str) -> Optional[str]:
    """Convert a supported Futu code into the analysis pipeline format."""

    prefix, separator, symbol = futu_code.partition(".")
    if not separator or not symbol:
        return None
    prefix = prefix.upper()
    symbol = symbol.upper()
    if prefix == "US":
        normalized = normalize_code(symbol)
        if normalized == symbol and is_us_stock_code(normalized):
            return normalized
        return None
    if prefix == "HK":
        normalized = normalize_code(f"HK.{symbol}")
        return f"HK{normalized}" if normalized is not None else None
    if prefix in {"SH", "SZ"}:
        normalized = normalize_code(f"{prefix}.{symbol}")
        return normalized if normalized == symbol else None
    return None


def _filter_stock_codes(
    api: _FutuApi,
    host: str,
    port: int,
    position_codes: List[str],
) -> List[str]:
    """Keep A/HK/US stocks and report unsupported Futu market codes."""

    if not position_codes:
        return []

    grouped: dict[str, List[str]] = {}
    unsupported_codes: List[str] = []
    for code in position_codes:
        prefix = _market_prefix(code)
        if prefix not in _SUPPORTED_ANALYSIS_MARKETS or _is_cn_b_share_code(code):
            unsupported_codes.append(code)
            continue
        grouped.setdefault(prefix, []).append(code)

    if not grouped:
        logger.warning(
            "已跳过 %d 个当前分析流程不支持的 Futu 持仓: %s",
            len(unsupported_codes),
            ", ".join(unsupported_codes),
        )
        return []

    stock_codes = set()
    classified_codes = set()
    context = None
    try:
        context = api.OpenQuoteContext(host=host, port=port)
        for prefix, codes in grouped.items():
            market = getattr(api.Market, prefix, None)
            if market is None:
                unsupported_codes.extend(codes)
                continue
            for start in range(0, len(codes), _STATIC_INFO_BATCH_SIZE):
                batch = codes[start : start + _STATIC_INFO_BATCH_SIZE]
                ret, data = context.get_stock_basicinfo(
                    market,
                    stock_type=api.SecurityType.STOCK,
                    code_list=batch,
                )
                if ret != api.RET_OK:
                    raise FutuPortfolioError(
                        f"查询 Futu 持仓证券类型失败（{prefix}）: {data}"
                    )
                for row in _iter_rows(data, "Futu 证券类型查询"):
                    code = str(row.get("code", "") or "").strip().upper()
                    if not code:
                        continue
                    stock_type = _enum_text(row.get("stock_type"))
                    if stock_type in _UNKNOWN_SECURITY_TYPES:
                        continue
                    classified_codes.add(code)
                    if stock_type == "STOCK":
                        stock_codes.add(code)
    except FutuPortfolioError:
        raise
    except Exception as exc:  # noqa: BLE001 - translate SDK/network errors for CLI callers
        raise FutuPortfolioError(f"查询 Futu 持仓证券类型失败: {exc}") from exc
    finally:
        _safe_close(context)

    missing_codes = [
        code
        for codes in grouped.values()
        for code in codes
        if code not in classified_codes
    ]
    if unsupported_codes:
        logger.warning(
            "已跳过 %d 个当前分析流程不支持的 Futu 持仓: %s",
            len(unsupported_codes),
            ", ".join(unsupported_codes),
        )
    if missing_codes:
        raise FutuPortfolioError(
            "无法确认证券类型的 Futu 持仓: " + ", ".join(missing_codes)
        )

    result: List[str] = []
    conversion_failures: List[str] = []
    for futu_code in position_codes:
        if futu_code not in stock_codes:
            continue
        analysis_code = _to_analysis_code(futu_code)
        if not analysis_code:
            conversion_failures.append(futu_code)
            continue
        if analysis_code not in result:
            result.append(analysis_code)
    if conversion_failures:
        raise FutuPortfolioError(
            "无法转换已确认的 Futu 正股代码到当前分析格式: "
            + ", ".join(conversion_failures)
        )
    return result


def load_futu_stock_codes() -> List[str]:
    """Return deduplicated analysis codes from all selected REAL Futu accounts.

    Only explicitly ACTIVE REAL accounts and Futu ``SecurityType.STOCK`` LONG
    positions with non-zero quantity are kept. ``FUTU_ACC_ID`` can select one
    account; otherwise NORMAL and MASTER accounts are merged. ``MASTER`` is an
    account role, while read-only describes this integration's query-only API
    calls. Firm discovery uses the SDK's ``SecurityFirm.NONE`` auto-detection
    unless ``FUTU_SECURITY_FIRM`` is explicitly set. Position data is always
    refreshed. Symbol conversion is limited to A/HK/US stocks; holdings from
    other Futu markets are logged with their codes and skipped.
    """
    api = _load_futu_api()
    host, port = _connection_settings()
    accounts = _discover_real_accounts(api, host, port)
    position_codes = _load_position_codes(api, host, port, accounts)
    stock_codes = _filter_stock_codes(api, host, port, position_codes)
    logger.info(
        "已从 Futu 真实账户加载 %d 只正股（账户数: %d，原始非零多头持仓数: %d）: %s",
        len(stock_codes),
        len(accounts),
        len(position_codes),
        ", ".join(stock_codes),
    )
    return stock_codes


def load_futu_broker_snapshot() -> FutuBrokerSnapshot:
    """Load accounts and live positions for the read-only Web account page.

    Connection details continue to come from server-side ``FUTU_*`` settings;
    the browser never receives or submits a Moomoo password or trading unlock
    credential. Only query APIs are used.
    """

    api = _load_futu_api()
    host, port = _connection_settings()
    accounts = _discover_real_accounts(api, host, port)
    positions: List[FutuPositionSnapshot] = []
    cash_balances: List[FutuCashBalanceSnapshot] = []
    position_counts: Dict[int, int] = {}
    account_metrics: Dict[int, Dict[str, Optional[float]]] = {}
    reporting_currency = "USD"

    for account in accounts:
        context = None
        try:
            context = api.OpenSecTradeContext(
                host=host,
                port=port,
                filter_trdmarket=api.TrdMarket.NONE,
                security_firm=account.security_firm,
            )
            query_currency = getattr(api.Currency, reporting_currency, None)
            accinfo_query = getattr(context, "accinfo_query", None)
            if callable(accinfo_query):
                accinfo_kwargs = {
                    "trd_env": api.TrdEnv.REAL,
                    "acc_id": account.acc_id,
                    "refresh_cache": True,
                }
                if query_currency is not None:
                    accinfo_kwargs["currency"] = query_currency
                info_ret, info_data = accinfo_query(**accinfo_kwargs)
                if info_ret != api.RET_OK:
                    raise FutuPortfolioError(f"查询 Futu 账户资产失败: {info_data}")
                info_rows = list(_iter_rows(info_data, "Futu 账户资产查询"))
                if not info_rows:
                    raise FutuPortfolioError("Futu 账户资产查询返回了空数据")
                info = info_rows[0]
                cash_balances.extend(_extract_cash_balances(account.acc_id, info))
                realized_pnl = _optional_finite_float(info.get("realized_pl"))
                unrealized_pnl = _optional_finite_float(info.get("unrealized_pl"))
                total_pnl = _sum_complete([realized_pnl, unrealized_pnl])
                account_market_value = _optional_finite_float(info.get("market_val"))
                total_assets = _optional_finite_float(info.get("total_assets"))
                account_metrics[account.acc_id] = {
                    "market_value": account_market_value,
                    "total_assets": total_assets,
                    "total_pnl": total_pnl,
                    "total_pnl_pct": _pnl_percentage(total_pnl, total_assets),
                }
            ret, data = context.position_list_query(
                trd_env=api.TrdEnv.REAL,
                acc_id=account.acc_id,
                refresh_cache=True,
                **({"currency": query_currency} if query_currency is not None else {}),
            )
            if ret != api.RET_OK:
                raise FutuPortfolioError(f"查询 Futu 真实持仓失败: {data}")
            count = 0
            for row in _iter_rows(data, "Futu 持仓查询"):
                side = _enum_text(row.get("position_side"))
                quantity = _optional_finite_float(row.get("qty"))
                if quantity is None:
                    raise FutuPortfolioError("Futu 持仓数量无效")
                if quantity == 0:
                    continue
                code = str(row.get("code", "") or "").strip().upper()
                if not code:
                    raise FutuPortfolioError("Futu 非零持仓返回了空证券代码")
                holding_pnl = _optional_finite_float(row.get("pl_val"))
                unrealized_pnl = _optional_finite_float(row.get("unrealized_pl"))
                positions.append(FutuPositionSnapshot(
                    account_id=account.acc_id,
                    code=code,
                    name=str(row.get("stock_name", "") or "").strip(),
                    position_side=side or "UNKNOWN",
                    quantity=quantity,
                    available_quantity=_optional_finite_float(
                        row.get("can_sell_qty")
                    ),
                    cost_price=_optional_finite_float(row.get("average_cost")),
                    current_price=_optional_finite_float(row.get("nominal_price")),
                    market_value=_optional_finite_float(row.get("market_val")),
                    holding_pnl=holding_pnl,
                    holding_pnl_pct=_optional_finite_float(
                        row.get("pl_ratio_avg_cost")
                    ),
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=_pnl_percentage(
                        unrealized_pnl,
                        _optional_finite_float(row.get("market_val")),
                    ),
                    realized_pnl=_optional_finite_float(row.get("realized_pl")),
                    today_pnl=_optional_finite_float(row.get("today_pl_val")),
                    today_change_pct=None,
                    currency=_enum_text(row.get("currency")) or reporting_currency,
                ))
                count += 1
            position_counts[account.acc_id] = count
            account_positions = [
                item for item in positions if item.account_id == account.acc_id
            ]
            metrics = account_metrics.setdefault(account.acc_id, {})
            position_fx_rates = _infer_position_fx_rates(
                account_positions,
                reporting_currency=reporting_currency,
                reporting_market_value=metrics.get("market_value"),
            )
            positions = [
                replace(
                    item,
                    exchange_rate_to_reporting_currency=position_fx_rates.get(
                        item.currency
                    ),
                )
                if item.account_id == account.acc_id
                else item
                for item in positions
            ]
            account_today_pnl = _sum_converted_position_field(
                account_positions,
                field="today_pnl",
                rates=position_fx_rates,
            )
            account_holding_pnl = _sum_converted_position_field(
                account_positions,
                field="holding_pnl",
                rates=position_fx_rates,
            )
            if account_holding_pnl is None:
                account_holding_pnl = metrics.get("total_pnl")
            metrics["holding_pnl"] = account_holding_pnl
            metrics["holding_pnl_pct"] = _pnl_percentage(
                account_holding_pnl,
                metrics.get("market_value"),
            )
            if metrics.get("total_pnl") is None:
                position_total_pnls = [
                    _sum_complete([item.realized_pnl, item.unrealized_pnl])
                    for item in account_positions
                ]
                converted_total_pnls = [
                    value * position_fx_rates[item.currency]
                    if value is not None and item.currency in position_fx_rates
                    else None
                    for item, value in zip(account_positions, position_total_pnls)
                ]
                metrics["total_pnl"] = _sum_complete(converted_total_pnls)
                metrics["total_pnl_pct"] = _pnl_percentage(
                    metrics.get("total_pnl"),
                    metrics.get("total_assets"),
                )
            metrics["today_pnl"] = account_today_pnl
            metrics["today_pnl_pct"] = _pnl_percentage(
                account_today_pnl,
                metrics.get("market_value"),
            )
        except FutuPortfolioError:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK/network error boundary
            raise FutuPortfolioError(f"查询 Futu 真实持仓失败: {exc}") from exc
        finally:
            _safe_close(context)

    today_changes = _load_today_change_percentages(
        api,
        host,
        port,
        positions,
    )
    positions = [
        replace(position, today_change_pct=today_changes.get(position.code))
        for position in positions
    ]

    account_snapshots = [
        FutuAccountSnapshot(
            account_id=account.acc_id,
            role=account.role,
            security_firm=_enum_text(account.security_firm) or "UNKNOWN",
            position_count=position_counts.get(account.acc_id, 0),
            currency=reporting_currency,
            market_value=account_metrics.get(account.acc_id, {}).get("market_value"),
            holding_pnl=account_metrics.get(account.acc_id, {}).get("holding_pnl"),
            holding_pnl_pct=account_metrics.get(account.acc_id, {}).get(
                "holding_pnl_pct"
            ),
            total_pnl=account_metrics.get(account.acc_id, {}).get("total_pnl"),
            total_pnl_pct=account_metrics.get(account.acc_id, {}).get("total_pnl_pct"),
            today_pnl=account_metrics.get(account.acc_id, {}).get("today_pnl"),
            today_pnl_pct=account_metrics.get(account.acc_id, {}).get("today_pnl_pct"),
        )
        for account in accounts
    ]
    total_market_value = _sum_complete(item.market_value for item in account_snapshots)
    holding_pnl = _sum_complete(item.holding_pnl for item in account_snapshots)
    total_pnl = _sum_complete(item.total_pnl for item in account_snapshots)
    today_pnl = _sum_complete(item.today_pnl for item in account_snapshots)
    total_assets = _sum_complete(
        account_metrics.get(item.account_id, {}).get("total_assets")
        for item in account_snapshots
    )
    return FutuBrokerSnapshot(
        host=host,
        port=port,
        currency=reporting_currency,
        total_market_value=total_market_value,
        holding_pnl=holding_pnl,
        holding_pnl_pct=_pnl_percentage(holding_pnl, total_market_value),
        total_pnl=total_pnl,
        total_pnl_pct=_pnl_percentage(total_pnl, total_assets),
        today_pnl=today_pnl,
        today_pnl_pct=_pnl_percentage(today_pnl, total_market_value),
        accounts=account_snapshots,
        positions=positions,
        cash_balances=cash_balances,
    )
