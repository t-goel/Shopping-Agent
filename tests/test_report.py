"""Terminal evaluation summary formatting (mock trials only)."""

from shopping_agent.contracts import TrialResult
from shopping_agent.eval.report import (
    common_failure_issue,
    format_run_summary,
    format_trial_line,
)


def trial(**overrides) -> TrialResult:
    base = dict(
        task_id="demo_task",
        task_version="suite-v4",
        catalog_version="catalog-v2",
        agent_name="claude",
        model_id=None,
        prompt_version=None,
        trial_number=1,
        mode="api",
        selected_product_ids=[],
        response_text="Trial failed.",
        constraints_satisfied=0,
        total_constraints=1,
        tool_calls=2,
        duration_seconds=0.4,
        termination_reason="unrecoverable_failure",
        is_successful=False,
        difficulty="easy",
        expected_kind="product",
        error="JSONDecodeError: Expecting value: line 1 column 1 (char 0)",
    )
    base.update(overrides)
    return TrialResult(**base)


def test_format_trial_line_marks_pass_and_fail():
    passed = trial(
        task_id="nl_cheapest_waterproof_jacket_m",
        is_successful=True,
        termination_reason="completed",
        error=None,
        response_text="ok",
        selected_product_ids=["ridge-shell"],
    )
    failed = trial(task_id="price_hike_recover_to_alternative", difficulty="hard")
    assert format_trial_line(passed) == "PASS  nl_cheapest_waterproof_jacket_m [easy]"
    assert format_trial_line(failed).startswith("FAIL  price_hike_recover_to_alternative [hard]")
    assert "JSONDecodeError" in format_trial_line(failed)


def test_format_run_summary_score_and_common_failure():
    records = [
        trial(task_id="a"),
        trial(task_id="b", difficulty="medium"),
        trial(
            task_id="c",
            difficulty="hard",
            error="ValueError: rules pilot requires structured Surface A input",
        ),
        trial(
            task_id="d",
            is_successful=True,
            termination_reason="completed",
            error=None,
            response_text="ok",
            selected_product_ids=["x"],
            difficulty="easy",
        ),
    ]
    text = format_run_summary(records)
    assert "PASS  d [easy]" in text
    assert text.count("FAIL") == 3
    assert "Score: 1/4 (25%)" in text
    assert "Common failure (2/3 failed): JSONDecodeError: Expecting value: line 1 column 1 (char 0)" in text
    assert common_failure_issue(records)[1] == 2


def test_all_pass_summary():
    records = [
        trial(
            task_id="ok",
            is_successful=True,
            termination_reason="completed",
            error=None,
            response_text="ok",
            selected_product_ids=["x"],
        )
    ]
    text = format_run_summary(records)
    assert "Score: 1/1 (100%)" in text
    assert "All trials passed." in text
    assert common_failure_issue(records) is None
