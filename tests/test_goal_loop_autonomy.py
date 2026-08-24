from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]  # リポジトリルート
sys.path.insert(0, str(ROOT))

from goal_loop_decision import decide  # noqa: E402


POLICY = ROOT / "goal_loop_policy.json"
GOAL_LOOP = ROOT / "GOAL_LOOP.md"


def ctx(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "dod_met": False,
        "writeback_complete": False,
        "writeback_required": True,
        "ai_safe_work_remaining": False,
        "minor_reversible_ambiguity": False,
        "failed_independent_approaches": 0,
        "same_method_retries": 0,
        "safe_alternative_available": False,
        "recovery_paths_exhausted": False,
        "human_action_remaining": False,
        "missing_authority": False,
        "irreversible_or_external": False,
    }
    base.update(overrides)
    return base


def main() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["default_action"] == "replan"
    assert policy["hard_block_after_independent_failures_without_alternative"] == 3
    assert policy["same_method_retry_limit"] == 1
    assert policy["defer_non_gating_human_decisions"] is True
    assert policy["writeback_required_by_default"] is True
    assert policy["decision_order"] == [
        "done",
        "continue_ai_safe_work",
        "resolve_writeback_gate",
        "recover_known_safe_alternative",
        "handoff_known_human_action",
        "hard_block_protected_or_exhausted",
        "continue_with_assumption",
        "replan_switch_from_retried_method",
        "replan_find_concrete_action",
    ]

    scenarios = {
        "incomplete_without_route": (ctx(), "replan"),
        "ai_safe_work_remains": (ctx(ai_safe_work_remaining=True), "continue"),
        "minor_reversible_ambiguity": (
            ctx(minor_reversible_ambiguity=True),
            "continue_with_assumption",
        ),
        "first_failure_has_alternative": (
            ctx(failed_independent_approaches=1, safe_alternative_available=True),
            "recover",
        ),
        "second_failure_has_alternative": (
            ctx(failed_independent_approaches=2, safe_alternative_available=True),
            "recover",
        ),
        "three_independent_failures": (
            ctx(failed_independent_approaches=3),
            "hard_block",
        ),
        "failed_ai_routes_but_human_path_exists": (
            ctx(failed_independent_approaches=3, human_action_remaining=True),
            "handoff",
        ),
        "human_wait_but_ai_work_remains": (
            ctx(human_action_remaining=True, ai_safe_work_remaining=True),
            "continue",
        ),
        "only_human_action_remains": (
            ctx(human_action_remaining=True),
            "handoff",
        ),
        "dod_met_writeback_pending": (ctx(dod_met=True), "continue"),
        "dod_and_writeback_complete": (
            ctx(dod_met=True, writeback_complete=True),
            "done",
        ),
        "read_only_writeback_not_required": (
            ctx(dod_met=True, writeback_required=False),
            "done",
        ),
        "missing_authority_but_safe_prep_remains": (
            ctx(missing_authority=True, ai_safe_work_remaining=True),
            "continue",
        ),
        "missing_authority_no_safe_work": (
            ctx(missing_authority=True),
            "hard_block",
        ),
        "external_action_no_safe_work": (
            ctx(irreversible_or_external=True),
            "hard_block",
        ),
        "writeback_pending_but_authority_missing": (
            ctx(dod_met=True, missing_authority=True),
            "hard_block",
        ),
        "known_human_external_action": (
            ctx(human_action_remaining=True, irreversible_or_external=True),
            "handoff",
        ),
        "only_route_proven_exhausted": (
            ctx(failed_independent_approaches=1, recovery_paths_exhausted=True),
            "hard_block",
        ),
        "same_method_retry_limit_reached": (
            ctx(same_method_retries=1),
            "replan",
        ),
        "single_failure_needs_new_plan": (
            ctx(failed_independent_approaches=1),
            "replan",
        ),
    }

    for name, (context, expected) in scenarios.items():
        actual = decide(context)
        assert actual == expected, f"{name}: expected={expected}, actual={actual}"

    precedence_guards = {
        "known_safe_route_after_three_failures": (
            ctx(failed_independent_approaches=3, safe_alternative_available=True),
            "recover",
        ),
        "route_specific_authority_block_has_fallback": (
            ctx(missing_authority=True, safe_alternative_available=True),
            "recover",
        ),
        "protected_action_is_not_minor_ambiguity": (
            ctx(missing_authority=True, minor_reversible_ambiguity=True),
            "hard_block",
        ),
        "human_wait_does_not_hide_safe_alternative": (
            ctx(human_action_remaining=True, safe_alternative_available=True),
            "recover",
        ),
        "writeback_handoff_does_not_hide_safe_alternative": (
            ctx(
                dod_met=True,
                human_action_remaining=True,
                safe_alternative_available=True,
            ),
            "recover",
        ),
    }
    for name, (context, expected) in precedence_guards.items():
        actual = decide(context)
        assert actual == expected, f"{name}: expected={expected}, actual={actual}"

    try:
        decide(ctx(recovery_paths_exhausted=True, safe_alternative_available=True))
    except ValueError:
        pass
    else:
        raise AssertionError("contradictory recovery state must be rejected")

    prose_contracts = {
        GOAL_LOOP: (
            "AI安全作業が残る限り",
            "独立した安全な回復手段を3つ",
            "同じ手段の再試行は1回まで",
            "判断キュー",
            "`REPLAN`",
            "全経路の不存在を証拠化",
            "目標達成ループ",
            "目標更新ループ",
            "直近の動き",
            "コンテキストの採用条件",
            "子ループ",
            "ズレ診断",
            "恒久化候補を1行",
            "自走・無人運用を名乗る場合の追加条件",
        ),
    }
    for path, required_phrases in prose_contracts.items():
        body = path.read_text(encoding="utf-8")
        for phrase in required_phrases:
            assert phrase in body, f"missing phrase in {path.name}: {phrase}"

    goal_loop_normative = GOAL_LOOP.read_text(encoding="utf-8").split(
        "## 設計の経緯", 1
    )[0]
    assert "ゴールループは外部ゴール管理ツールを必須としない" in goal_loop_normative
    assert "前提変化" in goal_loop_normative and "内部判定" in goal_loop_normative
    # 検討したうえで採用しなかった設計。再混入の検出用であって、
    # 一般に間違いだと主張するものではない。
    forbidden_merge_regressions = (
        "外部ゴール管理ツールを必須とする",
        "外部ゴール管理ツールは必須",
        "毎周、依頼者に質問して停止",
        "毎周「ゴールこのまま？」と質問",
    )
    for phrase in forbidden_merge_regressions:
        assert phrase not in goal_loop_normative, f"forbidden merge regression: {phrase}"

    print(
        f"PASS: {len(scenarios)}/{len(scenarios)} autonomy scenarios "
        f"+ {len(precedence_guards) + 1} precedence guards"
    )


def test_goal_loop_autonomy() -> None:
    """pytest から収集される入口。直接実行（`python <このファイル>`）と同じ検証を走らせる。

    この関数が無いと `pytest` はこのファイルからテストを1件も収集せず、
    "no tests ran" を返す。CI に載せた時に偽グリーンになるため、必ず残すこと。
    """
    main()


if __name__ == "__main__":
    main()
