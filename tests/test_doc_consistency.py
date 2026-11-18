"""Guard the names and numbers that the two papers quote from this repo.

Papers and slides are written from these sources, so a stale model ID, tool
name, budget, or suite count here propagates into the drafts. These checks keep
the prose tied to the code, config, and benchmark artifacts.
"""

import json
from pathlib import Path

import pytest

from shopping_agent.agent.agent import TOOLS, Agent

ROOT = Path(__file__).resolve().parents[1]

STALE_CLAIMS = (
    "Claude Haiku 5.5",
    "Haiku 5.5",
    "claude-haiku-5-5",
    "get_product_details",
    "get_listing_details",
    "10 attempted public tool calls",
)

TEXT_SOURCES = (
    "plan.md",
    "README.md",
    "docs/project-update-2.md",
    "docs/project-update-3.md",
    "docs/parallel-handoff.md",
    "docs/benchmark/related-work.md",
    "src/shopping_agent/agent/agent.py",
)


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", TEXT_SOURCES)
def test_no_stale_names_or_budgets_in_sources(relative):
    text = read(relative)
    for stale in STALE_CLAIMS:
        assert stale not in text, f"{relative} still contains {stale!r}"


def test_agent_default_model_matches_recorded_trials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert Agent(api_key="test").model == "claude-sonnet-4-5"
    assert "claude-sonnet-4-5" in read("plan.md")


def test_tool_surface_names_get_listing():
    names = {tool["name"] for tool in TOOLS}
    assert "get_listing" in names
    assert "get_product_details" not in names


def test_tool_call_budget_is_twenty():
    assert "twenty public tool calls" in read("README.md")
    assert "20 attempted public tool calls" in read("docs/project-update-2.md")


def test_suite_counts_match_benchmark_artifacts():
    summary = json.loads(read("docs/benchmark/task-summary.json"))
    assert summary["task_count"] == 10
    assert summary["difficulty_counts"] == {"easy": 3, "medium": 3, "hard": 4}

    for relative in ("plan.md", "docs/benchmark/related-work.md"):
        assert "3 easy / 3 medium / 4 hard" in read(relative)

    status = read("docs/project-update-3.md")
    assert "ten authored tasks" in status
    assert "five authored tasks" not in status
    assert "5/10 authored tasks" not in read("docs/benchmark/related-work.md")
