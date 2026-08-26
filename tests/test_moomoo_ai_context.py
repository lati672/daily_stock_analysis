# -*- coding: utf-8 -*-

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.brokers.futu.portfolio import FutuBrokerSnapshot, FutuPortfolioError, FutuPositionSnapshot
from src.services.moomoo_ai_context import enrich_moomoo_chat_context


def _position(code, currency, market_value, today_pnl, account_id=1001):
    return FutuPositionSnapshot(
        account_id=account_id,
        code=code,
        name=code,
        position_side="LONG",
        quantity=10,
        available_quantity=10,
        cost_price=100,
        current_price=110,
        market_value=market_value,
        holding_pnl=100,
        holding_pnl_pct=10,
        unrealized_pnl=80,
        unrealized_pnl_pct=8,
        realized_pnl=20,
        today_pnl=today_pnl,
        today_change_pct=2,
        currency=currency,
    )


def _snapshot(positions):
    return FutuBrokerSnapshot(
        host="127.0.0.1",
        port=11111,
        currency="USD",
        total_market_value=None,
        holding_pnl=None,
        holding_pnl_pct=None,
        total_pnl=None,
        total_pnl_pct=None,
        today_pnl=None,
        today_pnl_pct=None,
        accounts=[],
        positions=positions,
    )


class MoomooAiContextTest(unittest.TestCase):
    def test_builds_deterministic_attribution_without_account_metadata(self):
        snapshot = _snapshot([
            _position("US.AAPL", "USD", 1_000, 30, 1001),
            _position("US.NVDA", "USD", 3_000, -10, 2002),
        ])
        with patch("src.services.moomoo_ai_context.load_futu_broker_snapshot", return_value=snapshot):
            result = enrich_moomoo_chat_context({
                "include_moomoo_portfolio": True,
                "moomoo_context_mode": "today_attribution",
            })

        payload = result["moomoo_portfolio_context"]
        market = payload["markets"][0]
        self.assertEqual(market["total_today_pnl"], 20)
        self.assertEqual([item["code"] for item in market["positions"]], ["AAPL", "NVDA"])
        self.assertEqual(market["positions"][0]["weight_pct"], 25)
        self.assertEqual(market["positions"][0]["today_pnl_contribution_pct"], 150)
        serialized = json.dumps(payload)
        self.assertNotIn("account_id", serialized)
        self.assertNotIn("1001", serialized)
        self.assertNotIn("host", payload)
        self.assertNotIn("port", payload)

    def test_position_mode_filters_to_selected_hk_stock(self):
        snapshot = _snapshot([
            _position("US.AAPL", "USD", 1_000, 30),
            _position("HK.00700", "HKD", 2_000, 20),
        ])
        with patch("src.services.moomoo_ai_context.load_futu_broker_snapshot", return_value=snapshot):
            result = enrich_moomoo_chat_context({
                "stock_code": "HK00700",
                "include_moomoo_portfolio": True,
                "moomoo_context_mode": "position",
            })

        markets = result["moomoo_portfolio_context"]["markets"]
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0]["currency"], "HKD")
        self.assertEqual(markets[0]["positions"][0]["code"], "HK00700")

    def test_opt_out_does_not_load_opend(self):
        with patch("src.services.moomoo_ai_context.load_futu_broker_snapshot") as loader:
            result = enrich_moomoo_chat_context({"stock_code": "AAPL"})
        loader.assert_not_called()
        self.assertEqual(result, {"stock_code": "AAPL"})

    def test_opend_failure_is_non_fatal(self):
        with patch(
            "src.services.moomoo_ai_context.load_futu_broker_snapshot",
            side_effect=FutuPortfolioError("OpenD unavailable"),
        ):
            result = enrich_moomoo_chat_context({"include_moomoo_portfolio": True})
        self.assertEqual(result["moomoo_portfolio_context"]["status"], "unavailable")

    def test_agent_prompt_marks_portfolio_values_as_read_only_deterministic_context(self):
        from src.agent.executor import prepare_agent_chat

        with patch("src.agent.executor.build_visible_chat_history", return_value=[]):
            prepared = prepare_agent_chat(
                message="分析 AAPL",
                session_id="session-test",
                context={
                    "stock_code": "AAPL",
                    "moomoo_portfolio_context": {"status": "ok", "markets": []},
                },
                config=SimpleNamespace(),
                context_llm_adapter=None,
                skill_instructions="",
                default_skill_policy="",
                use_legacy_default_prompt=False,
                use_codex_prompt=False,
                include_provider_trace=False,
            )

        prompt = "\n".join(message["content"] for message in prepared.history_messages)
        self.assertIn("只读实时 Moomoo 持仓上下文", prompt)
        self.assertIn("不要重新推算", prompt)
        self.assertIn('"status": "ok"', prompt)


if __name__ == "__main__":
    unittest.main()
