from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal


Decision = Literal[
    "continue",
    "replan",
    "continue_with_assumption",
    "recover",
    "handoff",
    "hard_block",
    "done",
]

POLICY_PATH = Path(__file__).with_name("goal_loop_policy.json")
POLICY: dict[str, Any] = json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def decide(context: Mapping[str, object]) -> Decision:
    """Return the next goal-loop action from observable state only."""

    dod_met = bool(context.get("dod_met", False))
    writeback_complete = bool(context.get("writeback_complete", False))
    writeback_required = bool(
        context.get(
            "writeback_required", POLICY["writeback_required_by_default"]
        )
    )
    ai_safe_work_remaining = bool(context.get("ai_safe_work_remaining", False))
    minor_reversible_ambiguity = bool(
        context.get("minor_reversible_ambiguity", False)
    )
    failed_approaches = int(context.get("failed_independent_approaches", 0))
    same_method_retries = int(context.get("same_method_retries", 0))
    safe_alternative = bool(context.get("safe_alternative_available", False))
    recovery_paths_exhausted = bool(
        context.get("recovery_paths_exhausted", False)
    )
    human_action_remaining = bool(context.get("human_action_remaining", False))
    missing_authority = bool(context.get("missing_authority", False))
    irreversible_or_external = bool(
        context.get("irreversible_or_external", False)
    )
    failure_limit = int(
        POLICY["hard_block_after_independent_failures_without_alternative"]
    )
    same_method_retry_limit = int(POLICY["same_method_retry_limit"])

    if recovery_paths_exhausted and safe_alternative:
        raise ValueError(
            "safe_alternative_available and recovery_paths_exhausted cannot both be true"
        )

    if (
        dod_met
        and (writeback_complete or not writeback_required)
        and not human_action_remaining
    ):
        return "done"
    # A partial human blocker never cancels independent, authorized AI work.
    if ai_safe_work_remaining:
        return "continue"

    if dod_met and writeback_required and not writeback_complete:
        if safe_alternative:
            return "recover"
        if human_action_remaining:
            return "handoff"
        if missing_authority or irreversible_or_external:
            return "hard_block"
        if recovery_paths_exhausted or failed_approaches >= failure_limit:
            return "hard_block"
        if same_method_retries >= same_method_retry_limit:
            return "replan"
        return "continue"

    if safe_alternative:
        return "recover"
    if human_action_remaining:
        return "handoff"
    if missing_authority or irreversible_or_external:
        return "hard_block"
    if recovery_paths_exhausted or failed_approaches >= failure_limit:
        return "hard_block"
    if minor_reversible_ambiguity:
        return "continue_with_assumption"
    if same_method_retries >= same_method_retry_limit:
        return "replan"

    return str(POLICY["default_action"])  # type: ignore[return-value]
