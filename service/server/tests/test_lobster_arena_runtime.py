import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import database
from lobster_agent_runtime import (
    get_lobster_run,
    get_lobster_system_status,
    list_lobster_runs,
    run_lobster_agent_cycle,
)


class LobsterArenaRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_openai_key = os.environ.pop("OPENAI_API_KEY", None)
        self.old_llm_key = os.environ.pop("LLM_API_KEY", None)
        database._SQLITE_DB_PATH = os.path.join(self.tmp.name, "test.db")
        database.init_database()

    def tearDown(self) -> None:
        if self.old_openai_key is not None:
            os.environ["OPENAI_API_KEY"] = self.old_openai_key
        if self.old_llm_key is not None:
            os.environ["LLM_API_KEY"] = self.old_llm_key
        self.tmp.cleanup()

    def test_agent_cycle_records_history_and_broker_guardrail(self) -> None:
        result = run_lobster_agent_cycle(
            symbols=["NVDA", "AAPL"],
            initial_cash=100000,
            fee_rate=0.001,
            max_position=0.3,
            use_llm=False,
            publish_to_platform=False,
            include_api_agent=False,
            source="unit-test",
        )

        self.assertTrue(result["run_id"].startswith("lobster_"))
        self.assertEqual(result["broker_status"]["mode"], "paper")
        self.assertFalse(result["broker_status"]["live_orders_enabled"])
        self.assertTrue(result["risk_summary"]["paper_trading_only"])
        self.assertGreaterEqual(result["risk_summary"]["trade_count"], 0)

        history = list_lobster_runs(limit=5)
        self.assertEqual(history["count"], 1)
        self.assertEqual(history["runs"][0]["run_id"], result["run_id"])
        self.assertEqual(history["runs"][0]["source"], "unit-test")
        self.assertEqual(history["runs"][0]["status"], "ok")

        detail = get_lobster_run(result["run_id"])
        self.assertIsNotNone(detail)
        self.assertEqual(detail["result"]["run_id"], result["run_id"])
        self.assertEqual(detail["result"]["broker_status"]["status"], "paper_only")
        self.assertIn("agent_profiles", detail["result"])
        self.assertIn("agent_reports", detail["result"])
        self.assertIn("risk_events", detail["result"])
        self.assertGreaterEqual(len(detail["result"]["agent_reports"]), 1)

    def test_llm_missing_key_falls_back_to_local_reasons(self) -> None:
        result = run_lobster_agent_cycle(
            symbols=["NVDA"],
            initial_cash=100000,
            fee_rate=0.001,
            max_position=0.2,
            use_llm=True,
            publish_to_platform=False,
            include_api_agent=True,
            source="unit-test",
        )

        self.assertEqual(result["llm"]["status"], "not_configured")
        self.assertEqual(result["llm"]["fallback_reason"], "missing_llm_api_key")
        self.assertTrue(result["api_agent"]["enabled"])
        self.assertEqual(result["api_agent"]["llm_decision_permission"], "disabled")
        self.assertTrue(all("target_fraction" in item for item in result["decisions"]))

    def test_llm_failure_does_not_change_guardrailed_decisions(self) -> None:
        os.environ["LLM_API_KEY"] = "test-key"
        with patch("lobster_agent_runtime._chat_completion", side_effect=RuntimeError("boom")):
            result = run_lobster_agent_cycle(
                symbols=["NVDA"],
                initial_cash=100000,
                fee_rate=0.001,
                max_position=0.2,
                use_llm=True,
                publish_to_platform=False,
                include_api_agent=False,
                source="unit-test",
            )

        self.assertEqual(result["llm"]["status"], "error")
        self.assertEqual(result["llm"]["fallback_reason"], "llm_request_failed")
        for row in result["leaderboard"]:
            total_value = float(row["total_value"])
            for symbol, quantity in row["positions"].items():
                quote = next(item for item in result["quotes"] if item["symbol"] == symbol)
                exposure = float(quantity) * float(quote["price"]) / total_value
                self.assertLessEqual(exposure, 0.21)

    def test_system_status_exposes_demo_safety_flags(self) -> None:
        status = get_lobster_system_status()

        self.assertEqual(status["database"]["backend"], "sqlite")
        self.assertFalse(status["broker"]["live_orders_enabled"])
        self.assertTrue(status["paper_trading_only"])
        self.assertEqual(status["llm"]["decision_permission"], "explanation_only")


if __name__ == "__main__":
    unittest.main()
