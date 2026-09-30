from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from src.brokers.futu import portfolio as service


class _TradeContext:
    def __init__(
        self,
        *,
        filter_trdmarket,
        host,
        port,
        security_firm,
        accounts=None,
        positions_by_account=None,
    ) -> None:
        self.closed = False
        self.position_queries = []
        self.accinfo_queries = []
        self.accounts = accounts
        self.positions_by_account = positions_by_account
        self.open_arguments = {
            "filter_trdmarket": filter_trdmarket,
            "host": host,
            "port": port,
            "security_firm": security_firm,
        }

    def get_acc_list(self):
        if self.accounts is not None:
            return 0, pd.DataFrame(self.accounts)
        return 0, pd.DataFrame([
            {
                "acc_id": 1001,
                "trd_env": "REAL",
                "acc_role": "NORMAL",
                "acc_status": "ACTIVE",
                "security_firm": "FUTUSECURITIES",
            },
            {
                "acc_id": 2002,
                "trd_env": "SIMULATE",
                "acc_role": "NORMAL",
                "acc_status": "ACTIVE",
                "security_firm": "FUTUSECURITIES",
            },
        ])

    def position_list_query(self, **kwargs):
        self.position_queries.append(kwargs)
        if self.positions_by_account is not None:
            return 0, pd.DataFrame(
                self.positions_by_account.get(kwargs["acc_id"], [])
            )
        return 0, pd.DataFrame([
            {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
            {"code": "US.DRAM", "qty": 3, "position_side": "LONG"},
            {
                "code": "US.AAPL261218C200000",
                "qty": -1,
                "position_side": "LONG",
            },
            {"code": "HK.00700", "qty": 20, "position_side": "LONG"},
            {"code": "SH.600519", "qty": 0, "position_side": "LONG"},
            {"code": "SZ.000001", "qty": 8, "position_side": "LONG"},
        ])

    def accinfo_query(self, **kwargs):
        self.accinfo_queries.append(kwargs)
        return 0, pd.DataFrame([{
            "market_val": 1900.0,
            "total_assets": 2100.0,
            "realized_pl": 25.0,
            "unrealized_pl": 95.0,
            "currency": "USD",
        }])

    def close(self) -> None:
        self.closed = True


class _QuoteContext:
    def __init__(self, *, host, port, stock_types=None, market_snapshots=None) -> None:
        self.closed = False
        self.open_arguments = {"host": host, "port": port}
        self.market_snapshot_queries = []
        self.market_snapshots = market_snapshots or {}
        self.stock_types = {
            "US.AAPL": "STOCK",
            "US.DRAM": "ETF",
            "US.AAPL261218C200000": "DRVT",
            "HK.00700": "STOCK",
            "SZ.000001": "STOCK",
            "JP.7203": "STOCK",
            "JP.130A": "STOCK",
        } if stock_types is None else stock_types

    def get_stock_basicinfo(self, market, *, stock_type, code_list):
        return 0, pd.DataFrame([
            {"code": code, "stock_type": self.stock_types[code]}
            for code in code_list
            if code in self.stock_types
        ])

    def get_market_snapshot(self, code_list):
        self.market_snapshot_queries.append(code_list)
        return 0, pd.DataFrame([
            {"code": code, **self.market_snapshots[code]}
            for code in code_list
            if code in self.market_snapshots
        ])

    def close(self) -> None:
        self.closed = True


def _fake_api(
    trade_contexts,
    quote_contexts,
    *,
    accounts=None,
    positions_by_account=None,
    stock_types=None,
    market_snapshots=None,
):
    def open_trade_context(*, filter_trdmarket, host, port, security_firm):
        context = _TradeContext(
            filter_trdmarket=filter_trdmarket,
            host=host,
            port=port,
            security_firm=security_firm,
            accounts=accounts,
            positions_by_account=positions_by_account,
        )
        trade_contexts.append(context)
        return context

    def open_quote_context(*, host, port):
        context = _QuoteContext(
            host=host,
            port=port,
            stock_types=stock_types,
            market_snapshots=market_snapshots,
        )
        quote_contexts.append(context)
        return context

    return service._FutuApi(
        OpenQuoteContext=open_quote_context,
        OpenSecTradeContext=open_trade_context,
        Market=SimpleNamespace(US="US", HK="HK", SH="SH", SZ="SZ", JP="JP"),
        RET_OK=0,
        SecurityFirm=SimpleNamespace(
            NONE="N/A",
            FUTUSECURITIES="FUTUSECURITIES",
            FUTUSG="FUTUSG",
        ),
        SecurityType=SimpleNamespace(STOCK="STOCK"),
        TrdEnv=SimpleNamespace(REAL="REAL"),
        TrdMarket=SimpleNamespace(NONE="NONE"),
    )


def _account(
    acc_id,
    acc_role,
    *,
    acc_status="ACTIVE",
    security_firm="FUTUSECURITIES",
):
    return {
        "acc_id": acc_id,
        "trd_env": "REAL",
        "acc_role": acc_role,
        "acc_status": acc_status,
        "security_firm": security_firm,
    }


def _load_codes_for_accounts(accounts, positions_by_account):
    trade_contexts = []
    quote_contexts = []
    api = _fake_api(
        trade_contexts,
        quote_contexts,
        accounts=accounts,
        positions_by_account=positions_by_account,
    )
    with patch.dict(
        "os.environ",
        {},
        clear=True,
    ), patch.object(service, "_load_futu_api", return_value=api):
        result = service.load_futu_stock_codes()
    return result, trade_contexts


class FutuPortfolioServiceTest(unittest.TestCase):
    def test_load_futu_broker_snapshot_returns_live_position_fields(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [{
                    "code": "US.AAPL",
                    "stock_name": "Apple",
                    "qty": 10,
                    "can_sell_qty": 8,
                    "position_side": "LONG",
                    "cost_price": 175.0,
                    "average_cost": 180.5,
                    "diluted_cost": 175.0,
                    "nominal_price": 190.0,
                    "market_val": 1900.0,
                    "pl_val": 95.0,
                    "pl_ratio": 5.26,
                    "pl_ratio_avg_cost": 5.25,
                    "unrealized_pl": 95.0,
                    "realized_pl": 25.0,
                    "today_pl_val": 38.0,
                    "currency": "USD",
                }],
            },
            market_snapshots={
                "US.AAPL": {"last_price": 190.0, "prev_close_price": 185.0},
            },
        )

        account_info = pd.DataFrame([{
            "market_val": 1900.0,
            "total_assets": 2100.0,
            "realized_pl": "N/A",
            "unrealized_pl": "N/A",
            "currency": "USD",
            "au_cash": 3.57,
            "au_avl_withdrawal_cash": 3.57,
            "aud_net_cash_power": 3.57,
            "us_cash": 2790.37,
            "us_avl_withdrawal_cash": 1383.57,
            "usd_net_cash_power": 2790.37,
            "hk_cash": 720.36,
            "hk_avl_withdrawal_cash": 720.36,
            "hkd_net_cash_power": 720.36,
        }])
        with patch.dict("os.environ", {}, clear=True), patch.object(
            service, "_load_futu_api", return_value=api
        ), patch.object(
            _TradeContext, "accinfo_query", return_value=(0, account_info)
        ):
            snapshot = service.load_futu_broker_snapshot()

        self.assertEqual(snapshot.host, "127.0.0.1")
        self.assertEqual(snapshot.accounts[0].account_id, 1001)
        self.assertEqual(snapshot.accounts[0].role, "NORMAL")
        self.assertEqual(snapshot.accounts[0].position_count, 1)
        self.assertEqual(snapshot.positions[0].code, "US.AAPL")
        self.assertEqual(snapshot.positions[0].available_quantity, 8.0)
        self.assertEqual(snapshot.positions[0].cost_price, 180.5)
        self.assertEqual(snapshot.positions[0].holding_pnl, 95.0)
        self.assertEqual(snapshot.positions[0].holding_pnl_pct, 5.25)
        self.assertAlmostEqual(snapshot.positions[0].today_change_pct, 2.7027027)
        self.assertEqual(snapshot.positions[0].exchange_rate_to_reporting_currency, 1.0)
        self.assertAlmostEqual(snapshot.positions[0].unrealized_pnl_pct, 5.2631579)
        self.assertEqual(snapshot.total_market_value, 1900.0)
        self.assertEqual(snapshot.holding_pnl, 95.0)
        self.assertAlmostEqual(snapshot.holding_pnl_pct, 5.2631579)
        self.assertEqual(snapshot.total_pnl, 120.0)
        self.assertEqual(snapshot.today_pnl, 38.0)
        self.assertEqual(
            [(item.currency, item.cash) for item in snapshot.cash_balances],
            [("AUD", 3.57), ("USD", 2790.37), ("HKD", 720.36)],
        )
        self.assertEqual(snapshot.cash_balances[1].available_for_withdrawal, 1383.57)
        self.assertEqual(snapshot.cash_balances[1].net_cash_power, 2790.37)
        self.assertTrue(all(ctx.closed for ctx in trade_contexts))
        self.assertEqual(quote_contexts[0].market_snapshot_queries, [["US.AAPL"]])
        self.assertTrue(all(ctx.closed for ctx in quote_contexts))

    def _position_at_price(self, current_price: float) -> service.FutuPositionSnapshot:
        return service.FutuPositionSnapshot(
            account_id=1001,
            code="US.META",
            name="Meta Platforms",
            position_side="LONG",
            quantity=2.419,
            available_quantity=2.419,
            cost_price=649.898,
            current_price=current_price,
            market_value=current_price * 2.419,
            holding_pnl=193.58,
            holding_pnl_pct=12.31,
            unrealized_pnl=193.58,
            unrealized_pnl_pct=12.31,
            realized_pnl=117.26,
            today_pnl=-21.45,
            today_change_pct=None,
            currency="USD",
        )

    def _load_meta_today_change(self, current_price: float) -> float:
        api = _fake_api(
            [],
            [],
            market_snapshots={
                "US.META": {
                    "last_price": 738.79,
                    "prev_close_price": 715.62,
                    "pre_price": 730.0,
                    "pre_change_rate": -1.189,
                    "after_price": 743.3,
                    "after_change_rate": 0.61,
                }
            },
        )
        result = service._load_today_change_percentages(
            api,
            "127.0.0.1",
            11111,
            [self._position_at_price(current_price)],
        )
        return result["US.META"]

    def test_today_change_uses_premarket_quote_matching_nominal_price(self):
        self.assertEqual(self._load_meta_today_change(729.923), -1.189)

    def test_today_change_uses_regular_quote_matching_nominal_price(self):
        self.assertAlmostEqual(
            self._load_meta_today_change(738.79),
            3.2377518795,
        )

    def test_today_change_uses_after_hours_quote_matching_nominal_price(self):
        self.assertEqual(self._load_meta_today_change(743.28), 0.61)

    def test_mixed_usd_hkd_pnl_is_converted_to_account_usd(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {
                        "code": "US.AAPL", "stock_name": "Apple", "qty": 10,
                        "position_side": "LONG", "market_val": 1000.0,
                        "pl_val": 100.0, "unrealized_pl": 80.0,
                        "realized_pl": 20.0, "today_pl_val": 10.0,
                        "currency": "USD",
                    },
                    {
                        "code": "HK.00700", "stock_name": "Tencent", "qty": 20,
                        "position_side": "LONG", "market_val": 10000.0,
                        "pl_val": 1000.0, "unrealized_pl": 800.0,
                        "realized_pl": 200.0, "today_pl_val": 100.0,
                        "currency": "HKD",
                    },
                ],
            },
        )
        account_info = pd.DataFrame([{
            "market_val": 2280.0,
            "total_assets": 2500.0,
            "realized_pl": "N/A",
            "unrealized_pl": "N/A",
            "currency": "USD",
        }])

        with patch.dict("os.environ", {}, clear=True), patch.object(
            service, "_load_futu_api", return_value=api
        ), patch.object(
            _TradeContext, "accinfo_query", return_value=(0, account_info)
        ):
            snapshot = service.load_futu_broker_snapshot()

        self.assertAlmostEqual(snapshot.holding_pnl, 228.0)
        self.assertAlmostEqual(snapshot.today_pnl, 22.8)
        self.assertAlmostEqual(snapshot.total_pnl, 228.0)
        self.assertEqual(snapshot.currency, "USD")
        rates = {
            item.code: item.exchange_rate_to_reporting_currency
            for item in snapshot.positions
        }
        self.assertEqual(rates["US.AAPL"], 1.0)
        self.assertAlmostEqual(rates["HK.00700"], 0.128)

    def test_missing_sdk_uses_actionable_install_error(self):
        with patch(
            "builtins.__import__",
            side_effect=ImportError("No module named 'futu'"),
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "未安装 Futu OpenAPI SDK",
        ) as raised:
            service._load_futu_api()

        self.assertIn('pip install "futu-api==10.9.6908"', str(raised.exception))

    def test_sdk_initialization_failure_uses_portfolio_error_boundary(self):
        with patch(
            "builtins.__import__",
            side_effect=PermissionError("log directory denied"),
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "加载 Futu OpenAPI SDK 失败: log directory denied",
        ):
            service._load_futu_api()

    def test_load_futu_stock_codes_keeps_only_supported_a_hk_us_stocks(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(trade_contexts, quote_contexts)

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api):
            result = service.load_futu_stock_codes()

        self.assertEqual(result, ["AAPL", "HK00700", "000001"])
        position_contexts = [ctx for ctx in trade_contexts if ctx.position_queries]
        self.assertEqual(len(position_contexts), 1)
        self.assertEqual(
            position_contexts[0].position_queries,
            [{"trd_env": "REAL", "acc_id": 1001, "refresh_cache": True}],
        )
        self.assertTrue(all(ctx.closed for ctx in trade_contexts))
        self.assertTrue(quote_contexts and all(ctx.closed for ctx in quote_contexts))

    def test_load_futu_stock_codes_reports_unsupported_jp_holdings(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "JP.7203", "qty": 5, "position_side": "LONG"},
                    {"code": "JP.130A", "qty": 3, "position_side": "LONG"},
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertLogs(service.logger, level="WARNING") as captured:
            result = service.load_futu_stock_codes()

        self.assertEqual(result, [])
        warning_text = "\n".join(captured.output)
        self.assertIn("JP.7203", warning_text)
        self.assertIn("JP.130A", warning_text)

    def test_load_futu_stock_codes_keeps_supported_holdings_when_jp_is_present(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "JP.7203", "qty": 5, "position_side": "LONG"},
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertLogs(service.logger, level="WARNING") as captured:
            result = service.load_futu_stock_codes()

        self.assertEqual(result, ["AAPL"])
        self.assertIn("JP.7203", "\n".join(captured.output))

    def test_load_futu_stock_codes_rejects_stock_code_outside_analysis_contract(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "HK.BAD", "qty": 3, "position_side": "LONG"},
                ]
            },
            stock_types={"HK.BAD": "STOCK"},
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "无法转换.*HK.BAD",
        ):
            service.load_futu_stock_codes()

    def test_load_futu_stock_codes_reports_unsupported_b_shares(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "SH.900901", "qty": 5, "position_side": "LONG"},
                    {"code": "SZ.200012", "qty": 8, "position_side": "LONG"},
                ]
            },
            stock_types={
                "US.AAPL": "STOCK",
                "SH.900901": "STOCK",
                "SZ.200012": "STOCK",
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertLogs(
            service.logger,
            level="WARNING",
        ) as captured:
            result = service.load_futu_stock_codes()

        self.assertEqual(result, ["AAPL"])
        warning_text = "\n".join(captured.output)
        self.assertIn("SH.900901", warning_text)
        self.assertIn("SZ.200012", warning_text)

    def test_load_futu_stock_codes_rejects_partial_static_info_response(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "US.MSFT", "qty": 4, "position_side": "LONG"},
                ]
            },
            stock_types={"US.AAPL": "STOCK"},
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "无法确认证券类型.*US.MSFT",
        ):
            service.load_futu_stock_codes()

    def test_load_futu_stock_codes_rejects_unknown_static_security_type(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "US.MSFT", "qty": 4, "position_side": "LONG"},
                ]
            },
            stock_types={"US.AAPL": "STOCK", "US.MSFT": "N/A"},
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "无法确认证券类型.*US.MSFT",
        ):
            service.load_futu_stock_codes()

    def test_load_futu_stock_codes_rejects_invalid_eligible_account_id(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[
                _account("invalid", "NORMAL"),
                _account(1001, "NORMAL"),
            ],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "账户查询返回了无效账户 ID",
        ):
            service.load_futu_stock_codes()

        self.assertFalse(any(ctx.position_queries for ctx in trade_contexts))
        self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_rejects_nonpositive_or_fractional_account_id(self):
        for invalid_acc_id in (0, -1, 1001.5, True):
            with self.subTest(acc_id=invalid_acc_id):
                trade_contexts = []
                quote_contexts = []
                api = _fake_api(
                    trade_contexts,
                    quote_contexts,
                    accounts=[
                        _account(invalid_acc_id, "NORMAL"),
                        _account(1001, "NORMAL"),
                    ],
                    positions_by_account={
                        1001: [
                            {
                                "code": "US.AAPL",
                                "qty": 10,
                                "position_side": "LONG",
                            }
                        ]
                    },
                )

                with patch.dict(
                    "os.environ",
                    {},
                    clear=True,
                ), patch.object(
                    service,
                    "_load_futu_api",
                    return_value=api,
                ), self.assertRaisesRegex(
                    service.FutuPortfolioError,
                    "账户查询返回了无效账户 ID",
                ):
                    service.load_futu_stock_codes()

                self.assertFalse(any(ctx.position_queries for ctx in trade_contexts))
                self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_rejects_invalid_position_quantity(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "US.MSFT", "qty": "bad", "position_side": "LONG"},
                ]
            },
            stock_types={
                "US.AAPL": "STOCK",
                "US.MSFT": "STOCK",
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "持仓数量无效.*US.MSFT",
        ):
            service.load_futu_stock_codes()

        self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_rejects_blank_nonzero_position_code(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "", "qty": 5, "position_side": "LONG"},
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "非零持仓返回了空证券代码",
        ):
            service.load_futu_stock_codes()

        self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_rejects_missing_nonzero_long_code(self):
        with self.assertRaisesRegex(
            service.FutuPortfolioError,
            "非零持仓返回了无效证券代码",
        ):
            _load_codes_for_accounts(
                [_account(1001, "NORMAL")],
                {
                    1001: [
                        {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                        {"qty": 5, "position_side": "LONG"},
                    ]
                },
            )

    def test_load_futu_stock_codes_rejects_unqualified_nonzero_long_code(self):
        with self.assertRaisesRegex(
            service.FutuPortfolioError,
            "非零持仓返回了无效证券代码",
        ):
            _load_codes_for_accounts(
                [_account(1001, "NORMAL")],
                {
                    1001: [
                        {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                        {"code": "AAPL", "qty": 5, "position_side": "LONG"},
                    ]
                },
            )

    def test_load_futu_stock_codes_rejects_non_string_nonzero_long_codes(self):
        for invalid_code in (True, 123, b"US.AAPL"):
            with self.subTest(code=invalid_code), self.assertRaisesRegex(
                service.FutuPortfolioError,
                "非零持仓返回了无效证券代码",
            ):
                _load_codes_for_accounts(
                    [_account(1001, "NORMAL")],
                    {
                        1001: [
                            {
                                "code": "US.AAPL",
                                "qty": 10,
                                "position_side": "LONG",
                            },
                            {
                                "code": invalid_code,
                                "qty": 5,
                                "position_side": "LONG",
                            },
                        ]
                    },
                )

    def test_default_firm_uses_one_official_none_discovery_context(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(trade_contexts, quote_contexts)

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api):
            service.load_futu_stock_codes()

        self.assertEqual(
            [context.open_arguments for context in trade_contexts],
            [
                {
                    "filter_trdmarket": "NONE",
                    "host": "127.0.0.1",
                    "port": 11111,
                    "security_firm": "N/A",
                },
                {
                    "filter_trdmarket": "NONE",
                    "host": "127.0.0.1",
                    "port": 11111,
                    "security_firm": "FUTUSECURITIES",
                },
            ],
        )
        self.assertEqual(
            [context.open_arguments for context in quote_contexts],
            [{"host": "127.0.0.1", "port": 11111}],
        )

    def test_configured_security_firm_replaces_auto_detection(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[
                _account(
                    1001,
                    "NORMAL",
                    security_firm="FUTUSG",
                )
            ],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {"FUTU_SECURITY_FIRM": "FUTUSG"},
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api):
            result = service.load_futu_stock_codes()

        self.assertEqual(result, ["AAPL"])
        self.assertEqual(
            trade_contexts[0].open_arguments["security_firm"],
            "FUTUSG",
        )

    def test_unknown_security_firm_fails_before_opening_context(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(trade_contexts, quote_contexts)

        with patch.dict(
            "os.environ",
            {"FUTU_SECURITY_FIRM": "UNKNOWN"},
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "不支持的 FUTU_SECURITY_FIRM: UNKNOWN",
        ):
            service.load_futu_stock_codes()

        self.assertEqual(trade_contexts, [])
        self.assertEqual(quote_contexts, [])

    def test_configured_account_id_must_be_a_positive_integer(self):
        for configured_acc_id in ("0", "-1", "1.5"):
            with self.subTest(acc_id=configured_acc_id):
                trade_contexts = []
                quote_contexts = []
                api = _fake_api(trade_contexts, quote_contexts)

                with patch.dict(
                    "os.environ",
                    {"FUTU_ACC_ID": configured_acc_id},
                    clear=True,
                ), patch.object(
                    service,
                    "_load_futu_api",
                    return_value=api,
                ), self.assertRaisesRegex(
                    service.FutuPortfolioError,
                    "FUTU_ACC_ID 必须是正整数账户 ID",
                ):
                    service.load_futu_stock_codes()

                self.assertEqual(trade_contexts, [])
                self.assertEqual(quote_contexts, [])

    def test_account_discovery_failure_is_not_retried_or_partially_ignored(self):
        trade_contexts = []
        quote_contexts = []
        base_api = _fake_api(trade_contexts, quote_contexts)
        context = SimpleNamespace(
            get_acc_list=MagicMock(return_value=(1, "broker unavailable")),
            close=MagicMock(),
        )
        open_calls = []

        def open_trade_context(**kwargs):
            open_calls.append(kwargs)
            return context

        api = SimpleNamespace(**base_api.__dict__)
        api.OpenSecTradeContext = open_trade_context

        with patch.dict("os.environ", {}, clear=True), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "查询 Futu 真实账户失败: broker unavailable",
        ):
            service.load_futu_stock_codes()

        self.assertEqual(len(open_calls), 1)
        self.assertEqual(open_calls[0]["security_firm"], "N/A")
        context.close.assert_called_once_with()
        self.assertEqual(quote_contexts, [])

    def test_real_accounts_require_explicit_active_status(self):
        cases = {
            "missing": None,
            "n/a": "N/A",
            "unknown": "UNKNOWN",
            "disabled": "DISABLED",
        }
        for label, status in cases.items():
            with self.subTest(status=label):
                account = _account(1001, "NORMAL", acc_status=status)
                if label == "missing":
                    account.pop("acc_status")
                trade_contexts = []
                quote_contexts = []
                api = _fake_api(
                    trade_contexts,
                    quote_contexts,
                    accounts=[account],
                    positions_by_account={
                        1001: [
                            {
                                "code": "US.AAPL",
                                "qty": 10,
                                "position_side": "LONG",
                            }
                        ]
                    },
                )

                with patch.dict("os.environ", {}, clear=True), patch.object(
                    service,
                    "_load_futu_api",
                    return_value=api,
                ), self.assertRaisesRegex(
                    service.FutuPortfolioError,
                    "未找到状态为 ACTIVE",
                ):
                    service.load_futu_stock_codes()

                self.assertFalse(any(ctx.position_queries for ctx in trade_contexts))
                self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_keeps_active_master_account(self):
        result, trade_contexts = _load_codes_for_accounts(
            [_account(3003, "MASTER")],
            {
                3003: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ],
            },
        )

        self.assertEqual(result, ["AAPL"])
        position_contexts = [ctx for ctx in trade_contexts if ctx.position_queries]
        self.assertEqual(len(position_contexts), 1)
        self.assertEqual(position_contexts[0].position_queries[0]["acc_id"], 3003)

    def test_load_futu_stock_codes_merges_master_and_normal_accounts(self):
        result, trade_contexts = _load_codes_for_accounts(
            [_account(1001, "NORMAL"), _account(3003, "MASTER")],
            {
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ],
                3003: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "HK.00700", "qty": 20, "position_side": "LONG"},
                ],
            },
        )

        self.assertEqual(result, ["AAPL", "HK00700"])
        queried_account_ids = [
            context.position_queries[0]["acc_id"]
            for context in trade_contexts
            if context.position_queries
        ]
        self.assertEqual(queried_account_ids, [1001, 3003])

    def test_load_futu_stock_codes_skips_short_positions_before_deduplication(self):
        result, trade_contexts = _load_codes_for_accounts(
            [_account(1001, "NORMAL"), _account(3003, "MASTER")],
            {
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "SHORT"},
                    {"code": "HK.00700", "qty": 20, "position_side": "SHORT"},
                ],
                3003: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ],
            },
        )

        self.assertEqual(result, ["AAPL"])
        queried_account_ids = [
            context.position_queries[0]["acc_id"]
            for context in trade_contexts
            if context.position_queries
        ]
        self.assertEqual(queried_account_ids, [1001, 3003])

    def test_load_futu_stock_codes_skips_non_long_before_validating_fields(self):
        result, _ = _load_codes_for_accounts(
            [_account(1001, "NORMAL")],
            {
                1001: [
                    {"qty": "bad", "position_side": "SHORT"},
                    {"qty": None, "position_side": "N/A"},
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                ]
            },
        )

        self.assertEqual(result, ["AAPL"])

    def test_load_futu_stock_codes_skips_unknown_position_sides(self):
        result, _ = _load_codes_for_accounts(
            [_account(1001, "NORMAL")],
            {
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "N/A"},
                    {"code": "HK.00700", "qty": 20},
                    {"code": "JP.7203", "qty": 5, "position_side": "NONE"},
                ],
            },
        )

        self.assertEqual(result, [])

    def test_load_futu_stock_codes_rejects_non_finite_or_missing_quantities(self):
        for quantity in (float("nan"), float("inf"), float("-inf"), None, True):
            with self.subTest(quantity=quantity), self.assertRaisesRegex(
                service.FutuPortfolioError,
                "持仓数量无效.*US.AAPL",
            ):
                _load_codes_for_accounts(
                    [_account(1001, "NORMAL")],
                    {
                        1001: [
                            {
                                "code": "US.AAPL",
                                "qty": quantity,
                                "position_side": "LONG",
                            }
                        ],
                    },
                )

    def test_load_futu_stock_codes_skips_malaysian_ipo_accounts(self):
        result, trade_contexts = _load_codes_for_accounts(
            [_account(1001, "NORMAL"), _account(4004, "IPO")],
            {
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ],
                4004: [
                    {"code": "HK.00700", "qty": 20, "position_side": "LONG"}
                ],
            },
        )

        self.assertEqual(result, ["AAPL"])
        queried_account_ids = [
            context.position_queries[0]["acc_id"]
            for context in trade_contexts
            if context.position_queries
        ]
        self.assertEqual(queried_account_ids, [1001])

    def test_invalid_futu_account_id_fails_before_position_query(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(trade_contexts, quote_contexts)

        with patch.dict(
            "os.environ",
            {
                "FUTU_SECURITY_FIRM": "FUTUSECURITIES",
                "FUTU_ACC_ID": "9999",
            },
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "FUTU_ACC_ID 未匹配",
        ):
            service.load_futu_stock_codes()

        self.assertFalse(any(ctx.position_queries for ctx in trade_contexts))

    def test_to_analysis_code(self):
        cases = [
            ("US.MSFT", "MSFT"),
            ("US.BRK.B", "BRK.B"),
            ("HK.01810", "HK01810"),
            ("HK.700", "HK00700"),
            ("SZ.000001", "000001"),
            ("SH.600519", "600519"),
            ("HK.123456", None),
            ("HK.BAD", None),
            ("SH.1", None),
            ("SZ.1234567", None),
            ("US.AAICPRC", None),
            ("US.SPX", None),
            ("JP.9984", None),
            ("SG.D05", None),
        ]
        for futu_code, expected in cases:
            with self.subTest(futu_code=futu_code):
                self.assertEqual(service._to_analysis_code(futu_code), expected)

    def test_connection_settings_accepts_ipv4_and_hostnames(self):
        cases = {
            "default": (None, "127.0.0.1"),
            "explicit_ipv4": ("127.0.0.1", "127.0.0.1"),
            "remote_ipv4": ("192.168.1.10", "192.168.1.10"),
            "hostname": ("localhost", "localhost"),
            "remote_hostname": ("opend.internal", "opend.internal"),
            "padded": (" 127.0.0.1 ", "127.0.0.1"),
        }
        for label, (configured, expected_host) in cases.items():
            with self.subTest(host=label):
                env = {} if configured is None else {"FUTU_OPEND_HOST": configured}
                with patch.dict("os.environ", env, clear=True):
                    host, port = service._connection_settings()
                self.assertEqual(host, expected_host)
                self.assertEqual(port, 11111)

    def test_connection_settings_rejects_ipv6_literal(self):
        for host in ("::1", "[::1]", "2001:db8::1"):
            with self.subTest(host=host):
                with patch.dict(
                    "os.environ",
                    {"FUTU_OPEND_HOST": host},
                    clear=True,
                ), self.assertRaisesRegex(
                    service.FutuPortfolioError,
                    "网络层仅支持 IPv4",
                ):
                    service._connection_settings()


if __name__ == "__main__":
    unittest.main()
