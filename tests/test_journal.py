"""trader-journal tests: P&L and R math, statistics, verdicts and the CLI."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load

journal = load("trader-journal", "journal")


def trade(r_exit, entry=100.0, stop=99.0, qty=10, fees=0.0, followed=True, setup="orb"):
    return journal.build_trade("TST", entry, stop, r_exit, qty, fees, setup=setup, date="2026-10-23",
                               followed=followed)


class Math(unittest.TestCase):
    def test_reel_example_hits_one_r(self):
        t = journal.build_trade("tsla", 364.18, 358.32, 370.04, 8, target=370.04, date="2026-10-19",
                                followed=True)
        self.assertEqual(t["symbol"], "TSLA")
        self.assertEqual(t["risk_usd"], 46.88)
        self.assertEqual(t["pnl_net"], 46.88)
        self.assertEqual(t["r"], 1.0)

    def test_fees_come_out_of_the_result(self):
        t = trade(101.0, fees=2.0)
        self.assertEqual(t["pnl_gross"], 10.0)
        self.assertEqual(t["pnl_net"], 8.0)
        self.assertEqual(t["r"], 0.8)

    def test_gap_through_the_stop_is_worse_than_minus_one_r(self):
        self.assertEqual(trade(98.5)["r"], -1.5)

    def test_rejects_bad_input(self):
        with self.assertRaises(journal.JournalError):
            trade(101.0, stop=101.0)
        with self.assertRaises(journal.JournalError):
            trade(101.0, qty=0)
        with self.assertRaises(journal.JournalError):
            trade(101.0, fees=-1)
        with self.assertRaises(journal.JournalError):
            journal.build_trade("TST", 100.0, 99.0, 101.0, 1, target=99.5)
        with self.assertRaises(ValueError):
            journal.build_trade("TST", 100.0, 99.0, 101.0, 1, date="23/10/2026")

    def test_followed_answer(self):
        self.assertTrue(journal.parse_followed("Oui"))
        self.assertFalse(journal.parse_followed("non"))
        with self.assertRaises(journal.JournalError):
            journal.parse_followed("peut-être")


class Stats(unittest.TestCase):
    def test_summary_numbers(self):
        ts = [trade(101.0), trade(99.0), trade(102.0), trade(99.0), trade(99.0)]
        s = journal.summarize(ts)
        self.assertEqual(s["trades"], 5)
        self.assertEqual(s["wins"], 2)
        self.assertEqual(s["win_rate"], 0.4)
        self.assertEqual(s["pnl_net"], 0.0)
        self.assertEqual(s["avg_r"], 0.0)
        self.assertEqual(s["profit_factor"], 1.0)
        self.assertEqual(s["max_drawdown"], 20.0)
        self.assertEqual(s["worst_losing_streak"], 2)

    def test_too_few_trades_says_too_early(self):
        s = journal.summarize([trade(102.0)] * 10)
        self.assertEqual(journal.verdict(s)[0], "TROP TOT")

    def test_coin_flip_has_no_proven_edge(self):
        s = journal.summarize([trade(101.0), trade(99.0)] * 20)
        self.assertEqual(journal.verdict(s)[0], "PAS DE PREUVE D'AVANTAGE")

    def test_steady_losses_are_called_losing(self):
        s = journal.summarize([trade(101.0), trade(99.0), trade(99.0)] * 12)
        self.assertEqual(journal.verdict(s)[0], "PERDANT")

    def test_clear_edge_is_probable_not_certain(self):
        s = journal.summarize([trade(102.0), trade(102.0), trade(99.0)] * 12)
        self.assertEqual(journal.verdict(s)[0], "AVANTAGE PROBABLE")

    def test_report_splits_plan_discipline_and_setups(self):
        ts = [trade(101.0), trade(98.0, followed=False, setup="bull_flag")]
        text, s = journal.report(ts)
        self.assertIn("plan non respecté", text)
        self.assertIn("bull_flag", text)
        self.assertEqual(s["followed_rate"], 0.5)

    def test_empty_report(self):
        text, s = journal.report([])
        self.assertIn("Aucun trade", text)
        self.assertEqual(s["trades"], 0)


class Cli(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.file = os.path.join(self.dir, "trader", "journal.json")
        self.plan = os.path.join(self.dir, "trader", "plan.json")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = journal.main(["--file", self.file] + list(args))
        return code, out.getvalue(), err.getvalue()

    def test_add_list_stats_remove(self):
        code, out, _ = self.run_cli("add", "--symbol", "TSLA", "--entry", "364.18", "--stop", "358.32",
                                    "--exit", "370.04", "--qty", "8", "--followed", "oui", "--date", "2026-10-19")
        self.assertEqual(code, 0)
        self.assertIn("Trade #1", out)
        self.run_cli("add", "--symbol", "AMD", "--entry", "50", "--stop", "49", "--exit", "48.5", "--qty", "10",
                     "--followed", "non", "--note", "stop déplacé")
        code, out, _ = self.run_cli("list")
        self.assertIn("stop déplacé", out)
        code, out, _ = self.run_cli("stats", "--json")
        s = json.loads(out)
        self.assertEqual(s["trades"], 2)
        self.assertEqual(s["verdict"], "TROP TOT")
        code, out, _ = self.run_cli("remove", "--id", "1")
        self.assertEqual(code, 0)
        with open(self.file, encoding="utf-8") as fh:
            self.assertEqual([t["id"] for t in json.load(fh)["trades"]], [2])

    def test_add_from_plan(self):
        os.makedirs(os.path.dirname(self.plan))
        with open(self.plan, "w") as fh:
            json.dump({"symbol": "TSLA", "entry": 364.18, "stop": 358.32, "target": 370.04, "setup": "orb",
                       "date": "2026-10-19"}, fh)
        code, out, _ = self.run_cli("add", "--from-plan", "--plan", self.plan, "--exit", "358.32", "--qty", "8",
                                    "--followed", "oui")
        self.assertEqual(code, 0)
        with open(self.file, encoding="utf-8") as fh:
            t = json.load(fh)["trades"][0]
        self.assertEqual((t["setup"], t["r"], t["date"]), ("orb", -1.0, "2026-10-19"))

    def test_errors_exit_one_without_writing(self):
        code, _, err = self.run_cli("add", "--symbol", "TSLA", "--entry", "10", "--stop", "11", "--exit", "12",
                                    "--qty", "1", "--followed", "oui")
        self.assertEqual(code, 1)
        self.assertIn("Erreur", err)
        self.assertFalse(os.path.exists(self.file))
        code, _, err = self.run_cli("add", "--from-plan", "--plan", self.plan, "--exit", "1", "--qty", "1",
                                    "--followed", "oui")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
