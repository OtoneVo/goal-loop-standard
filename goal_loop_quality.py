"""Bounded quality gate; no model calls, scheduler or authority changes."""
from __future__ import annotations

import copy
import json
import math
import os
import uuid
from pathlib import Path


def select_mode(facts):
    reasons = [key for key in ("multiple_steps", "cross_file_change", "uncertain_result",
               "high_impact", "previous_verification_failed") if facts.get(key) is True]
    return {"mode": "quality" if reasons else "minimal", "reasons": reasons or ["small_observable_task"]}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("expected finite nonnegative number")
    return value


def criteria_valid(criteria):
    if not criteria or len({c["id"] for c in criteria}) != len(criteria):
        raise ValueError("unique nonempty criteria required")
    for c in criteria:
        if not c["id"] or not c["check"]:
            raise ValueError("observable check required")
        number(c["tolerance"])


def start(goal, criteria, limits=None):
    criteria_valid(criteria)
    if not goal:
        raise ValueError("goal required")
    bounds = {"iterations": 8, "elapsed_seconds": 1800, "cost": 0, "stagnation": 3}
    bounds.update(limits or {})
    for value in bounds.values():
        number(value)
    for key in ("iterations", "stagnation"):
        if not isinstance(bounds[key], int) or bounds[key] < 1:
            raise ValueError("positive integer limits required")
    return {"schema": 1, "goal": goal, "criteria": copy.deepcopy(criteria), "limits": bounds,
            "iterations": 0, "elapsed_seconds": 0, "cost": 0, "stagnation": 0,
            "best": None, "history": [], "goal_changes": [], "status": "unmet",
            "residuals": [], "next_actions": [], "pending": []}


def evaluate(state, observations, *, elapsed_seconds, cost=0, review=None,
             regression=None, writeback=None, pending=None, interrupted=False):
    """Consume one externally measured round; caller supplies cumulative usage.

    review/regression/writeback: {passed: bool, evidence: str}. Evidence is a reference,
    not an authenticated assertion; callers must verify it against real outputs.
    """
    s = copy.deepcopy(state)
    criteria_valid(s["criteria"])
    number(elapsed_seconds)
    number(cost)
    if elapsed_seconds < s["elapsed_seconds"] or cost < s["cost"]:
        raise ValueError("cumulative usage cannot decrease on resume")
    ids = {c["id"] for c in s["criteria"]}
    if set(observations) - ids:
        raise ValueError("unknown criterion")
    residuals = []
    for c in s["criteria"]:
        o = observations.get(c["id"], {})
        measured = o.get("residual")
        if measured is not None:
            number(measured)
        evidence = o.get("evidence")
        passed = measured is not None and measured <= c["tolerance"] and isinstance(evidence, str) and bool(evidence.strip())
        residuals.append({"id": c["id"], "residual": measured, "tolerance": c["tolerance"],
                          "evidence": evidence, "passed": passed, "check": c["check"]})
    def gate(value):
        return isinstance(value, dict) and value.get("passed") is True and isinstance(value.get("evidence"), str) and bool(value["evidence"].strip())
    s.update(iterations=s["iterations"] + 1, elapsed_seconds=elapsed_seconds, cost=cost,
             residuals=residuals, pending=copy.deepcopy(pending or []))
    s["next_actions"] = [{"id": r["id"], "check": r["check"]} for r in residuals if not r["passed"]]
    if not gate(review):
        s["next_actions"].append({"id": "independent_review", "check": "fresh reviewer verifies current artifact"})
    if not gate(regression):
        s["next_actions"].append({"id": "regression", "check": "run relevant regression on current artifact"})
    if not gate(writeback):
        s["next_actions"].append({"id": "writeback", "check": "persist verified results to authorized state"})
    # Compare residual vectors, not output counts or an invented quality percentage.
    vector = [r["residual"] if r["evidence"] else None for r in residuals]
    best = s["best"]
    improves = best is None or (all(v is not None for v in vector) and
        (any(v is None for v in best) or (all(a <= b for a, b in zip(vector, best)) and any(a < b for a, b in zip(vector, best)))))
    s["stagnation"] = 0 if improves else s["stagnation"] + 1
    if improves:
        s["best"] = vector
    exceeded = [key for key in ("iterations", "elapsed_seconds", "cost", "stagnation") if s[key] >= s["limits"][key]]
    # Zero cost allows local computation; paid usage is blocked.
    if cost == 0 and s["limits"]["cost"] == 0:
        exceeded.remove("cost")
    if s["status"] == "unmet_budget":
        status = "unmet_budget"  # A fresh resume never resets exhausted limits.
    elif interrupted:
        status = "interrupted"
    elif pending:
        status = "blocked"
    elif cost > s["limits"]["cost"] or elapsed_seconds > s["limits"]["elapsed_seconds"] or s["iterations"] > s["limits"]["iterations"]:
        status = "unmet_budget"
    elif all(r["passed"] for r in residuals) and not s["next_actions"]:
        status = "done"
    elif exceeded:
        status = "unmet_budget" if any(k != "stagnation" for k in exceeded) else "unmet_stagnation"
    else:
        status = "continue"
    s["status"] = status
    s["history"].append({"iteration": s["iterations"], "status": status, "residuals": copy.deepcopy(residuals),
                         "review": review, "regression": regression, "writeback": writeback, "limits_reached": exceeded})
    return s


def can_execute(state, *, elapsed_seconds, reserved_cost=0):
    """Preflight before any next action; budgets survive resume."""
    number(elapsed_seconds)
    number(reserved_cost)
    if elapsed_seconds < state["elapsed_seconds"]:
        raise ValueError("cumulative elapsed time cannot decrease")
    reasons = []
    if state.get("pending"):
        reasons.append("pending")
    if state["status"] in ("done", "unmet_budget", "unmet_stagnation", "interrupted", "blocked"):
        reasons.append(state["status"])
    for key, value in (("iterations", state["iterations"]), ("elapsed_seconds", elapsed_seconds), ("stagnation", state["stagnation"])):
        if value >= state["limits"][key]:
            reasons.append(key)
    if state["cost"] + reserved_cost > state["limits"]["cost"]:
        reasons.append("cost")
    return {"allowed": not reasons, "reasons": reasons}


def revise_goal(state, goal, criteria, reason):
    if not reason.strip():
        raise ValueError("goal change reason required")
    criteria_valid(criteria)
    s = copy.deepcopy(state)
    s["goal_changes"].append({"old_goal": s["goal"], "new_goal": goal, "old_criteria": s["criteria"],
                              "new_criteria": copy.deepcopy(criteria), "reason": reason})
    s.update(goal=goal, criteria=copy.deepcopy(criteria), best=None, stagnation=0,
             status="unmet", residuals=[], next_actions=[])
    return s  # usage and limits survive goal changes


def save_checkpoint(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_checkpoint(path):
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    if state.get("schema") != 1:
        raise ValueError("unsupported checkpoint schema")
    criteria_valid(state["criteria"])
    for key in ("iterations", "elapsed_seconds", "cost", "stagnation"):
        number(state[key])
    return state
