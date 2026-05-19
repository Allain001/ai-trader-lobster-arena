import os
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import database
from lobster_agent_runtime import get_lobster_run, list_lobster_runs, run_lobster_agent_cycle


class LobsterArenaRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        database._SQLITE_DB_PATH = os.path.join(self.tmp.name, "test.db")
        database.init_database()

    def tearDown(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
