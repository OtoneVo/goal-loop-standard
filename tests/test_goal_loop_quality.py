import math
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from goal_loop_quality import start, evaluate, select_mode, save_checkpoint, load_checkpoint, revise_goal, can_execute, pending_key, resolve_pending, resume
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

    def test_pending_survives_checkpoint_success_and_empty_update(self):
        s = self.round(self.state(), 0, pending=[{"kind": "approval", "action": "publish"}])
        p = Path(__file__).resolve().parent / ("checkpoint-" + uuid.uuid4().hex + ".json")
        try:
            save_checkpoint(p, s)
            resumed = load_checkpoint(p)
            for kw in ({}, {"pending": []}, {"pending": [{"kind": "dependency", "action": "input"}]}):
                result = self.round(resumed, 0, **kw)
                self.assertEqual(result["status"], "blocked")
                self.assertIn(s["pending"][0], result["pending"])
                self.assertFalse(can_execute(result, elapsed_seconds=10)["allowed"])
        finally:
            if p.exists(): p.unlink()

    def test_pending_resolution_needs_trusted_authority(self):
        s = self.round(self.state(), 0, pending=[{"kind": "approval", "action": "publish"}])
        key = pending_key(s["pending"][0])
        for verifier in (None, lambda *a: False, lambda *a: "true"):
            with self.assertRaises(PermissionError):
                resolve_pending(s, key, evidence="approval.log", authority="owner", verify_authorization=verifier)
        with self.assertRaises(ValueError):
            resolve_pending(s, key, evidence="", authority="owner", verify_authorization=lambda *a: True)
        verified = []
        def trusted(item, actor, ref):
            verified.append((item, actor, ref))
            return item["action"] == "publish" and actor == "owner" and ref == "approval.log"
        cleared = resolve_pending(s, key, evidence="approval.log", authority="owner", verify_authorization=trusted)
        self.assertTrue(verified)
        self.assertTrue(s["pending"])
        self.assertEqual(cleared["iterations"], s["iterations"])
        self.assertEqual(cleared["pending_resolutions"][0]["item"], s["pending"][0])
        self.assertEqual(self.round(cleared, 0)["status"], "done")

    def test_checkpoint_resume_without_spending_round(self):
        s = self.round(self.state(), interrupted=True)
        p = Path(__file__).resolve().parent / ("checkpoint-" + uuid.uuid4().hex + ".json")
        try:
            save_checkpoint(p, s)
            loaded = load_checkpoint(p)
            restarted = resume(loaded, elapsed_seconds=10)
            self.assertTrue(can_execute(restarted, elapsed_seconds=10)["allowed"])
            for field in ("iterations", "elapsed_seconds", "cost", "stagnation", "limits"):
                self.assertEqual(restarted[field], s[field])
            self.assertEqual(loaded["status"], "interrupted")
            with self.assertRaises(PermissionError): resume(loaded, elapsed_seconds=1800)
            with self.assertRaises(PermissionError): resume(loaded, elapsed_seconds=10, reserved_cost=1)
        finally:
            if p.exists(): p.unlink()

    def test_resume_time_high_water_cannot_rewind(self):
        s = self.round(self.state(), interrupted=True)
        restarted = resume(s, elapsed_seconds=1700)
        self.assertEqual(restarted["elapsed_seconds"], 10)
        self.assertEqual(restarted["elapsed_high_water"], 1700)
        for action in (lambda: resume(restarted, elapsed_seconds=11),
                       lambda: can_execute(restarted, elapsed_seconds=11),
                       lambda: self.round(restarted, elapsed_seconds=11)):
            with self.assertRaises(ValueError): action()
        self.assertTrue(can_execute(restarted, elapsed_seconds=1700)["allowed"])

    def test_resume_preserves_pending_and_exhausted_limits(self):
        for s in (self.round(self.state(), interrupted=True, pending=[{"kind": "approval", "action": "publish"}]),
                  self.round(self.state(iterations=1), interrupted=True),
                  self.round(self.state(iterations=1)),
                  self.round(self.round(self.state(stagnation=1)))):
            before = s.copy()
            with self.assertRaises(PermissionError): resume(s, elapsed_seconds=10)
            self.assertEqual(s, before)

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
