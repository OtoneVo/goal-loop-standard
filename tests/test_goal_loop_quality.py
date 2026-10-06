import math
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from goal_loop_quality import start, evaluate, select_mode, save_checkpoint, load_checkpoint, revise_goal, can_execute
from goal_loop_decision import decide


class QualityTests(unittest.TestCase):
    def state(self, **limits):
        return start("observable result", [{"id": "correctness", "check": "fixture comparison", "tolerance": 0}], limits)

    def round(self, state, residual=1, **kw):
        args = dict(elapsed_seconds=10, review={"passed": True, "evidence": "review.log"},
                    regression={"passed": True, "evidence": "test.log"}, writeback={"passed": True, "evidence": "state.json"})
        args.update(kw)
        return evaluate(state, {"correctness": {"residual": residual, "evidence": "fixture.log"}}, **args)

    def test_modes(self):
        self.assertEqual(select_mode({})["mode"], "minimal")
        self.assertEqual(select_mode({"multiple_steps": True})["reasons"], ["multiple_steps"])

    def test_preflight(self):
        self.assertTrue(can_execute(self.state(), elapsed_seconds=0)["allowed"])
        self.assertFalse(can_execute(self.state(), elapsed_seconds=0, reserved_cost=1)["allowed"])
        self.assertFalse(can_execute(self.state(), elapsed_seconds=1800)["allowed"])

    def test_writeback_recovery_limit(self):
        self.assertEqual(decide({"dod_met": True, "recovery_paths_exhausted": True}), "hard_block")
        self.assertEqual(decide({"dod_met": True, "same_method_retries": 1}), "replan")

    def test_verified_done(self):
        self.assertEqual(self.round(self.state(), 0)["status"], "done")

    def test_false_green_and_review_failure(self):
        for extra in ({"review": None}, {"regression": {"passed": False, "evidence": "failure.log"}}, {"writeback": None},
                      {"writeback": {"passed": "false", "evidence": "state.json"}}, {"writeback": {"passed": True, "evidence": ""}}):
            self.assertNotEqual(self.round(self.state(), 0, **extra)["status"], "done")
        self.assertNotEqual(evaluate(self.state(), {}, elapsed_seconds=1)["status"], "done")

    def test_limits_and_resume(self):
        for limits, kw in (({"iterations": 1}, {}), ({"elapsed_seconds": 1}, {}), ({}, {"cost": 1})):
            s = self.round(self.state(**limits), **kw)
            self.assertEqual(s["status"], "unmet_budget")
            p = Path(__file__).resolve().parent / ("checkpoint-" + uuid.uuid4().hex + ".json")
            try:
                save_checkpoint(p, s)
                resumed = load_checkpoint(p)
                self.assertEqual(resumed, s)
                self.assertNotEqual(self.round(resumed, 0, cost=s["cost"])["status"], "done")
            finally:
                if p.exists():
                    p.unlink()

    def test_interrupted_and_approval(self):
        s = self.round(self.state(), interrupted=True)
        self.assertEqual(s["status"], "interrupted")
        self.assertEqual(self.round(s, 0)["status"], "done")
        s = self.round(self.state(), 0, pending=[{"kind": "approval", "action": "publish"}])
        self.assertEqual(s["status"], "blocked")
        self.assertTrue(s["pending"])

    def test_stagnation_and_goal_change(self):
        s = self.state(stagnation=1)
        s = self.round(s)
        s = self.round(s)
        self.assertEqual(s["status"], "unmet_stagnation")
        changed = revise_goal(s, "new", s["criteria"], "requirement changed")
        self.assertEqual(changed["iterations"], 2)
        self.assertEqual(changed["goal_changes"][0]["old_goal"], "observable result")

    def test_invalid_measurements(self):
        for v in (-1, math.nan, math.inf, True):
            with self.assertRaises(ValueError):
                self.round(self.state(), v)
        with self.assertRaises(ValueError):
            self.round(self.round(self.state()), elapsed_seconds=0)


if __name__ == "__main__":
    unittest.main()
