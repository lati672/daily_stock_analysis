# -*- coding: utf-8 -*-
"""Generate and deliver a read-only post-close Moomoo portfolio digest."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from src.config import Config, get_config
from src.services.moomoo_ai_context import enrich_moomoo_chat_context

logger = logging.getLogger(__name__)


class MoomooDailyReportError(RuntimeError):
    """Raised when a portfolio digest cannot be generated or delivered."""


class MoomooDailyReportService:
    """Build one portfolio digest and send it only to Discord."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or get_config()

    @staticmethod
    def _prompt(report_language: str) -> str:
        if report_language == "en":
            return (
                "Generate today's post-close portfolio digest from the read-only Moomoo context. "
                "Use the provided deterministic amounts without recalculating them. Include: "
                "(1) P/L attribution by market and the largest positive/negative contributors; "
                "(2) concentration, highlighting positions at or above 15%; "
                "(3) material news for at most five top contributors or concentrated positions, "
                "using search_stock_news when available and clearly saying when news is unavailable; "
                "(4) concise watch conditions for the next trading session. Separate facts from "
                "inference, preserve each market's currency, do not expose account identifiers, and "
                "do not place or claim to place trades. Return readable Markdown, not JSON."
            )
        return (
            "请根据系统提供的只读 Moomoo 持仓生成今日收盘后的持仓日报。直接使用程序已经确定性计算的"
            "金额与比例，不要重新推算。日报必须包含：1）按市场的盈亏归因及主要正负贡献；"
            "2）集中度，并突出仓位达到或超过 15% 的证券；3）最多五个主要贡献者或集中持仓的重大新闻，"
            "可用时调用 search_stock_news，无法取得新闻时必须明确说明；4）下一交易日值得关注的价格、"
            "事件和风险条件。请区分事实与推断，保留各市场原币种，不暴露账户标识，不执行或声称执行交易。"
            "使用清晰、紧凑的 Markdown，不要输出 JSON。"
        )

    def generate(self) -> Dict[str, Any]:
        """Load holdings, run the Agent, and return the generated Markdown."""
        enriched = enrich_moomoo_chat_context(
            {
                "include_moomoo_portfolio": True,
                "moomoo_context_mode": "today_attribution",
                "report_language": getattr(self.config, "report_language", "zh"),
            }
        )
        portfolio_context = enriched.get("moomoo_portfolio_context")
        if not isinstance(portfolio_context, dict) or portfolio_context.get("status") != "ok":
            message = (
                portfolio_context.get("message")
                if isinstance(portfolio_context, dict)
                else "Moomoo portfolio context is unavailable"
            )
            raise MoomooDailyReportError(str(message or "Moomoo portfolio context is unavailable"))
        if not portfolio_context.get("markets"):
            raise MoomooDailyReportError("Moomoo 当前没有可生成日报的持仓")

        from src.agent.factory import build_agent_chat_executor

        report_language = str(getattr(self.config, "report_language", "zh") or "zh").lower()
        symbols = [
            str(position.get("code") or "").strip()
            for market in portfolio_context.get("markets") or []
            if isinstance(market, dict)
            for position in market.get("positions") or []
            if isinstance(position, dict) and str(position.get("code") or "").strip()
        ]
        symbol_scope = ", ".join(dict.fromkeys(symbols))
        prompt = self._prompt(report_language)
        if symbol_scope:
            prompt += (
                f"\n\nPortfolio symbols explicitly in scope for news comparison: {symbol_scope}."
                if report_language == "en"
                else f"\n\n本次新闻比较明确限定在这些持仓证券：{symbol_scope}。"
            )
        executor = build_agent_chat_executor(self.config)
        result = executor.chat(
            prompt,
            session_id=f"moomoo-daily-report-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:8]}",
            context={
                "report_language": report_language,
                "moomoo_portfolio_context": portfolio_context,
            },
        )
        if not result.success or not str(result.content or "").strip():
            raise MoomooDailyReportError(result.error or "AI 未生成持仓日报")
        return {
            "content": str(result.content).strip(),
            "provider": result.provider,
            "model": result.model,
            "position_count": sum(
                len(market.get("positions") or [])
                for market in portfolio_context.get("markets") or []
                if isinstance(market, dict)
            ),
        }

    def generate_and_send(self) -> Dict[str, Any]:
        """Generate the digest and deliver it exclusively through Discord."""
        generated = self.generate()
        from src.notification import NotificationService

        title = (
            "Moomoo Portfolio Daily Digest"
            if str(getattr(self.config, "report_language", "zh")).lower() == "en"
            else "Moomoo 持仓日报"
        )
        content = f"## {title} · {datetime.now():%Y-%m-%d}\n\n{generated['content']}"
        if not NotificationService().send_to_discord(content):
            raise MoomooDailyReportError("Discord 未配置或持仓日报发送失败")
        logger.info("Moomoo daily portfolio report sent to Discord")
        return {**generated, "sent": True}
