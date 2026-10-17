"""End-to-end tests against a live FalkorDB. Skipped if none is reachable.

Uses a separate tenant graph so the demo graph is untouched.
"""

import asyncio

import pytest

from firebreak import agents, incidents, tools as T
from firebreak import simulator as sim
from firebreak.brain import answer
from firebreak.db import client, rows
from firebreak.seed import seed

TENANT = "pytest"


@pytest.fixture(scope="module")
def g():
    try:
        client().list_graphs()
    except Exception:
        pytest.skip("FalkorDB not reachable")
    graph = seed(TENANT)
    yield graph
    graph.delete()


@pytest.fixture(autouse=True)
def clean(g):
    yield
    sim.reset(g)


def test_seed_counts(g):
    assert rows(g, "MATCH (c:Component) RETURN count(c) AS n")[0]["n"] == 35
    assert rows(g, "MATCH (i:Incident) RETURN count(i) AS n")[0]["n"] >= 15


def test_indexes_exist(g):
    labels = {r["label"] for r in rows(g, "CALL db.indexes() YIELD label RETURN label")}
    assert {"Component", "Incident", "Decision", "Change"} <= labels


def test_blast_radius_and_impact(g):
    blast = {r["component"] for r in T.blast_radius(g, "auth-service").data}
    assert {"checkout-api", "payouts-api", "web-bff"} <= blast
    customers = {r["customer"] for r in T.business_impact(g, "auth-service").data}
    assert "Acme Retail" in customers


@pytest.mark.parametrize("sid", list(sim.SCENARIOS))
def test_scenario_end_to_end(g, sid):
    s = sim.SCENARIOS[sid]
    out = sim.inject(g, sid)
    iid = incidents.open_incident(g)
    v = asyncio.run(agents.investigate(g, iid))
    assert v["root_cause"] == (out["change"] or s.root)
    assert v["confidence"] > 0.7
    assert v["actions"][0]["kind"] == s.remediation
    # Detective and Responder coordinated through the graph: both left steps there.
    d = incidents.detail(g, iid)
    assert {st["agent"] for st in d["steps"]} == {"commander", "detective", "responder"}
    assert any(h["status"] == "rejected" and h["change"] == out["decoy"] for h in d["hypotheses"])

    incidents.approve_action(g, v["actions"][0]["id"])
    assert not rows(g, "MATCH (c:Component) WHERE c.status <> 'healthy' RETURN c.name")
    assert incidents.detail(g, iid)["status"] == "resolved"


def test_ask_cites_adr(g):
    a = answer(g, "Why does checkout call auth synchronously?")
    assert a["sources"][0]["id"] == "ADR-014"
    assert "auth-service" in a["highlight"]


def test_pagerank_ranks_shared_dependencies_highest(g):
    from firebreak import graph_algos

    pr = graph_algos.pagerank(g)
    assert len(pr.scores) == 35
    # Shared datastores carry most of the graph's dependency weight.
    assert {"postgres-main", "kafka-events"} <= {r["component"] for r in pr.top(5)}
    # The most depended-on component must clearly outrank a leaf caller.
    assert pr.scores["postgres-main"] > 2 * pr.scores["web-bff"]
    assert pr.cypher.startswith("CALL algo.pageRank")


def test_betweenness_finds_choke_points(g):
    from firebreak import graph_algos

    bw = graph_algos.betweenness(g)
    top = {r["component"] for r in bw.top(5)}
    assert {"checkout-api", "payments-core"} <= top
    spof = graph_algos.spof_scan(g, top=3)
    assert len(spof) == 3
    assert all(s["team"] and s["betweenness"] > 0 for s in spof)
    # Deterministic: pinned sampling seed gives the same scores twice.
    assert graph_algos.betweenness(g).scores == bw.scores


def test_pagerank_feeds_rca_criticality(g):
    """The RCA engine uses algorithm output, not a fan-in proxy."""
    from firebreak import simulator as sim
    from firebreak import tools as T

    sim.inject(g, "bad-deploy")
    from firebreak.incidents import open_incident
    iid = open_incident(g)
    alerting = from_alerting(g, iid)
    ranked, _, calls = T.rank_root_causes(g, alerting, sim.now_ms())
    assert any(c.tool == "pagerank" for c in calls)
    assert ranked[0].component == "auth-service"


def from_alerting(g, iid):
    from firebreak.incidents import alerting_components

    return alerting_components(g, iid)
