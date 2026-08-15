"""Tests for chapter 06 — the checks, which are the whole contribution.

The verifier is the only thing standing between a dropped constraint and a
confident wrong answer, so it gets tested harder than the loop around it.
"""

from __future__ import annotations

from conftest import load_run
from dataagent.llm import Reply, ToolCall
from dataagent.testing import ScriptedLLM

run = load_run(__file__)
Requirements = run.Requirements
check_sql, make_run_sql_tool = run.check_sql, run.make_run_sql_tool
run_agent, StopReason = run.run_agent, run.StopReason

PLAN_JSON = (
    '{"metric": "average total amount", "grouping": "zone_name", "filters": [], '
    '"min_count": 500, "sort": "highest", "limit": 1, "answerable": true, '
    '"reason": "top zone by average fare with at least 500 trips"}'
)


def reqs(**kw):
    base = {"metric": "m", "answerable": True, "reason": "r"}
    return Requirements(**{**base, **kw})


# ── The min-count check: the reason this chapter exists ──────────────────────


def test_missing_having_is_rejected_with_the_exact_fix():
    problem = check_sql(
        "SELECT z.zone_name, avg(t.total_amount), COUNT(*) FROM trips t "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
        reqs(min_count=500),
    )
    assert problem is not None
    assert "HAVING COUNT(*) >= 500" in problem, "must name the exact clause to add"


def test_having_count_satisfies_the_check():
    assert (
        check_sql(
            "SELECT z.zone_name, avg(x), COUNT(*) FROM t GROUP BY 1 "
            "HAVING COUNT(*) >= 500 ORDER BY 2 DESC LIMIT 1",
            reqs(min_count=500),
        )
        is None
    )


def test_no_min_count_means_no_having_requirement():
    assert check_sql("SELECT count(*) FROM trips", reqs()) is None


# ── Sample size must be visible ──────────────────────────────────────────────


def test_grouping_without_count_is_rejected():
    problem = check_sql("SELECT borough, avg(tip_amount) FROM t GROUP BY borough", reqs())
    assert problem is not None and "COUNT(*)" in problem


def test_grouping_with_count_passes():
    assert (
        check_sql("SELECT borough, avg(tip_amount), COUNT(*) FROM t GROUP BY borough", reqs())
        is None
    )


def test_limit_is_required_when_the_question_asks_for_n_rows():
    problem = check_sql("SELECT zone_name FROM zones", reqs(limit=5))
    assert problem is not None and "LIMIT 5" in problem


# ── Answer the name, not the id ──────────────────────────────────────────────


def test_selecting_a_bare_zone_id_is_rejected():
    """The real failure: 'zone 132 has the most trips' instead of 'JFK Airport'."""
    problem = check_sql(
        "SELECT pickup_zone_id, COUNT(*) FROM trips GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
        reqs(),
    )
    assert problem is not None and "name the thing" in problem


def test_a_zone_id_only_in_a_join_condition_is_fine():
    """zone_id belongs in ON clauses; it must not trip the check there."""
    assert (
        check_sql(
            "SELECT z.zone_name, COUNT(*) FROM trips t "
            "JOIN zones z ON t.pickup_zone_id = z.zone_id GROUP BY z.zone_name",
            reqs(),
        )
        is None
    )


# ── The tool wrapper ─────────────────────────────────────────────────────────


def test_failing_sql_never_reaches_the_database():
    tool = make_run_sql_tool(reqs(min_count=500), [3])
    out = tool.handler(sql="SELECT borough, avg(tip_amount), COUNT(*) FROM trips GROUP BY 1")
    assert out.startswith("CHECK FAILED")
    assert "HAVING" in out


def test_compliant_sql_executes_for_real():
    tool = make_run_sql_tool(reqs(min_count=1000), [3])
    out = tool.handler(
        sql="SELECT z.borough, avg(t.tip_amount) AS avg_tip, COUNT(*) AS n "
        "FROM trips t JOIN zones z ON t.pickup_zone_id = z.zone_id "
        "GROUP BY z.borough HAVING COUNT(*) >= 1000 ORDER BY avg_tip DESC LIMIT 1"
    )
    assert "Queens" in out, "the correct answer to the trap question"
    assert "Staten Island" not in out, "the trap answer must be excluded by HAVING"


def test_the_check_budget_stops_an_infinite_argument():
    """A verifier that can deadlock the agent is worse than one that gives up."""
    budget = [2]
    tool = make_run_sql_tool(reqs(min_count=500), budget)
    bad = "SELECT borough, avg(x), COUNT(*) FROM trips GROUP BY 1"

    assert tool.handler(sql=bad).startswith("CHECK FAILED")
    assert tool.handler(sql=bad).startswith("CHECK FAILED")
    # Budget exhausted: the query is now allowed through rather than looping.
    assert not tool.handler(sql=bad).startswith("CHECK FAILED")


def test_empty_results_blame_the_filter_not_the_data():
    """The baseline kept saying 'no such data' when its filter was simply wrong."""
    tool = make_run_sql_tool(reqs(), [3])
    out = tool.handler(sql="SELECT * FROM zones WHERE borough = 'Atlantis'")
    assert out.startswith("EMPTY RESULT")
    assert "sample_column" in out, "must point at the tool that finds real values"


def test_dangerous_sql_is_still_blocked():
    tool = make_run_sql_tool(reqs(), [3])
    assert tool.handler(sql="DROP TABLE trips").startswith("REJECTED")


# ── Planning ─────────────────────────────────────────────────────────────────


def test_an_unanswerable_question_short_circuits_before_any_sql():
    llm = ScriptedLLM(
        [
            Reply(
                text='{"metric": "driver earnings", "filters": [], "answerable": false, '
                '"reason": "the warehouse has no driver identities"}'
            )
        ]
    )
    result = run_agent(llm, "Which driver earned the most?")
    assert result.stop_reason is StopReason.UNANSWERABLE
    assert result.grounded, "declining without querying is correct behaviour"
    assert llm.call_count == 1, "must not waste a query on an impossible question"


def test_a_plan_that_never_validates_falls_back_instead_of_crashing():
    llm = ScriptedLLM([Reply(text="not json")] * 3 + [Reply(text="I cannot answer.")])
    result = run_agent(llm, "how many trips?")
    assert result.requirements.metric == "unknown"
    assert result.stop_reason is StopReason.ANSWERED


def test_the_agreed_plan_is_carried_into_the_system_prompt():
    """The model must not be able to forget a constraint it just agreed to."""
    llm = ScriptedLLM([Reply(text=PLAN_JSON), Reply(text="JFK Airport, at $77.73.")])
    run_agent(llm, "top zone by fare with at least 500 trips?")
    system = llm.calls[1].system
    assert "min_count" in system.lower() or "MINIMUM 500" in system
    assert "500" in system


def test_a_check_failure_is_counted_and_reported():
    call = ToolCall("t1", "run_sql", {"sql": "SELECT borough, avg(x) FROM trips GROUP BY 1"})
    llm = ScriptedLLM([Reply(text=PLAN_JSON), Reply(tool_calls=[call]), Reply(text="done")])
    result = run_agent(llm, "top zone with at least 500 trips?")
    assert result.checks_failed == 1
    assert result.steps[0].results[0].startswith("CHECK FAILED")
