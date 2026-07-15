from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from bot import ai_signals
from bot import risk_manager as rm
from bot.performance import closed_trades_from_events, symbol_expectancy
from bot.signals import Action, Signal
from bot.trading_controls import cooldown_active, record_stop_cooldown


class EdgeControlsTests(unittest.TestCase):
    def _ai_inputs(self):
        index = pd.date_range("2026-01-01", periods=20, freq="min", tz="UTC")
        df = pd.DataFrame(
            {
                "open": range(100, 120),
                "high": range(101, 121),
                "low": range(99, 119),
                "close": range(100, 120),
                "volume": [1000] * 20,
            },
            index=index,
        )
        inst = SimpleNamespace(asset_class="equity")
        signal = Signal("SPY", Action.LONG, 119, 1.0, 2.0, "secret strategy detail")
        return inst, df, signal

    def test_ai_mock_requires_two_labeled_mock_proposals(self) -> None:
        inst, df, signal = self._ai_inputs()
        with tempfile.TemporaryDirectory() as directory, patch(
            "bot.ai_signals.config.AI_DECISIONS_JSONL",
            str(Path(directory) / "ai.jsonl"),
        ), patch("bot.ai_signals.config.AI_SIGNAL_MODE", "paper_mock"):
            decision = ai_signals.approve_entry(inst, df, signal)
            self.assertTrue(decision.approved)
            self.assertEqual(decision.reason, "paper_mock")
            self.assertEqual(len(decision.proposals), 2)
            journal = (Path(directory) / "ai.jsonl").read_text()
            self.assertNotIn("secret strategy detail", journal)
            self.assertNotIn("closed_bars", journal)

    def test_ai_rejects_invalid_provider_payload(self) -> None:
        inst, df, signal = self._ai_inputs()
        context = ai_signals._context(inst, df, signal)
        invalid = '{"symbol":"SPY","bar_timestamp":"wrong","action":"long","allow_entry":true,"reason_code":"ok"}'
        self.assertIsNone(ai_signals._parse("test", "model", invalid, context, 1))

    def test_ai_requires_both_provider_approvals(self) -> None:
        inst, df, signal = self._ai_inputs()
        context = ai_signals._context(inst, df, signal)
        response = json.dumps(
            {
                "symbol": context["symbol"],
                "bar_timestamp": context["bar_timestamp"],
                "action": context["proposed_action"],
                "allow_entry": True,
                "reason_code": "approved",
            }
        )
        reject = response.replace("true", "false")
        with tempfile.TemporaryDirectory() as directory, patch(
            "bot.ai_signals.config.AI_DECISIONS_JSONL",
            str(Path(directory) / "ai.jsonl"),
        ), patch("bot.ai_signals.config.AI_SIGNAL_MODE", "providers"), patch(
            "bot.ai_signals.config.AI_ANTHROPIC_API_KEY", "key"
        ), patch("bot.ai_signals.config.AI_OPENAI_API_KEY", "key"), patch(
            "bot.ai_signals._ask_anthropic", return_value=response
        ), patch("bot.ai_signals._ask_openai", return_value=reject):
            self.assertFalse(ai_signals.approve_entry(inst, df, signal).approved)

    def test_regime_blocks_risk_on_shorts_and_risk_off_longs(self) -> None:
        self.assertEqual(rm.entry_regime_multiplier("equity", Action.LONG, False), 0.0)
        self.assertEqual(rm.entry_regime_multiplier("equity", Action.SHORT, True), 0.0)
        self.assertEqual(rm.entry_regime_multiplier("equity", Action.LONG, True), 1.0)

    def test_notional_cap_respects_whole_share_requirement(self) -> None:
        self.assertEqual(rm.cap_size_to_available_notional(10, 100, 250, False), 2.0)
        self.assertEqual(rm.cap_size_to_available_notional(10, 100, 250, True), 2.5)

    def test_stop_cooldown_expires(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, patch(
            "bot.trading_controls.STOP_COOLDOWN_STATE_FILE",
            str(Path(directory) / "cooldowns.json"),
        ):
            record_stop_cooldown("SPY", 20, now)
            self.assertTrue(cooldown_active("SPY", now))
            self.assertFalse(
                cooldown_active("SPY", datetime(2026, 1, 1, 0, 21, tzinfo=timezone.utc))
            )

    def test_performance_uses_confirmed_fill_rows_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trades.csv"
            with path.open("w", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "timestamp", "instrument", "direction", "entry_price",
                        "exit_price", "profit_loss", "position_size", "reason",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "timestamp": "2026-01-01T00:00:00+00:00",
                            "instrument": "SPY", "direction": "long",
                            "entry_price": "100", "exit_price": "",
                            "profit_loss": "", "position_size": "1",
                            "reason": "ENTRY [broker_fill]: test",
                        },
                        {
                            "timestamp": "2026-01-01T00:01:00+00:00",
                            "instrument": "SPY", "direction": "exit_long",
                            "entry_price": "100", "exit_price": "101",
                            "profit_loss": "1", "position_size": "1",
                            "reason": "EXIT [broker_fill]: test",
                        },
                    ]
                )
            trades = closed_trades_from_events(path)
            self.assertEqual(len(trades), 1)
            self.assertGreater(trades[0].r_multiple, 0)
            self.assertEqual(symbol_expectancy(trades)["SPY"]["closed_trades"], 1)


if __name__ == "__main__":
    unittest.main()
