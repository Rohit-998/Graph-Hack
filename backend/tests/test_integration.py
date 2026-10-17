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


@pytest.mark.parametrize("sid", [sp["id"] for sp in sim.SCENARIO_SPECS])
def test_scenario_end_to_end(g, sid):
    s = sim.scenario_map(g)[sid]
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


def test_preflight_ranks_risky_changes_above_safe_ones(g):
    from firebreak import preflight

    risky = preflight.check(g, "auth-service", "deploy")
    safe = preflight.check(g, "email-worker", "deploy")
    assert risky["risk"] == "high" and safe["risk"] == "low"
    assert risky["score"] > safe["score"]
    # Memory feeds prevention: the past incident caused by a deploy here is cited.
    assert any(p["id"] == "INC-2093" for p in risky["past_incidents"])
    assert any("INC-2093" in a for a in risky["advice"])
    # The decision that made auth a hard dependency is surfaced, with reviewers who know it.
    assert any(d["id"] == "ADR-014" for d in risky["decisions"])
    assert risky["reviewers"] and risky["reviewers"][0]["name"] == "Priya Raman"
    # Every factor is listed and bounded, so the score is auditable.
    assert all(0 <= v <= 1 for v in risky["factors"].values())


def test_conversation_persists_and_resolves_follow_ups(g):
    from firebreak import conversation as C

    a = C.ask(g, "priya", "Why does checkout call auth synchronously?")
    cid = a["conversation"]
    assert a["sources"][0]["id"] == "ADR-014"
    # "it" resolves by walking from the previous answer's cited Decision to its deciders.
    b = C.ask(g, "priya", "Who decided it?", cid)
    assert b["follow_up_of"] and "Aisha Bello" in b["answer"] and "Hana Kim" in b["answer"]
    # History is in the graph, ordered, with citations kept.
    h = C.history(g, "priya", cid)
    assert [m["role"] for m in h] == ["user", "assistant", "user", "assistant"]
    assert h[1]["cites"][0] == "ADR-014"
    assert any(c["id"] == cid for c in C.conversations(g, "priya"))


def test_conversation_memory_is_per_user(g):
    import pytest as _pt
    from firebreak import conversation as C

    cid = C.ask(g, "priya", "How do I fail over from Stripe?")["conversation"]
    with _pt.raises(PermissionError):
        C.history(g, "marcus", cid)
    with _pt.raises(PermissionError):
        C.ask(g, "marcus", "and then?", cid)
    assert not any(c["id"] == cid for c in C.conversations(g, "marcus"))


def test_ingested_ticket_is_linked_searchable_and_marks_decision_stale(g):
    from firebreak import knowledge as K
    from firebreak.brain import answer

    r = K.ingest(g, "ticket", "Session tokens expiring early on mobile",
                 "auth-service returns 401 for refresh tokens. Priya Raman suspects the pool change. "
                 "See ADR-014 and INC-2093.", author="marcus", status="open")
    links = r["links"]
    assert "auth-service" in links["components"] and "priya" in links["people"]
    assert {x["id"] for x in links["references"]} == {"ADR-014", "INC-2093"}
    # Searchable by the company brain straight away.
    assert answer(g, "refresh tokens expiring mobile")["sources"][0]["id"] == r["id"]
    # The decision it references is now flagged for re-review, with the ticket as evidence.
    stale = {x["id"]: x for x in K.stale(g)}
    assert r["id"] in stale["ADR-014"]["evidence"]


def test_stale_runbook_clears_after_review(g):
    from firebreak import knowledge as K

    assert "RB-001" in {x["id"] for x in K.stale(g)}
    K.mark_reviewed(g, "RB-001", "priya")
    assert "RB-001" not in {x["id"] for x in K.stale(g)}


def test_readonly_cypher_is_enforced_by_the_database(g):
    import pytest as _pt
    from firebreak import cypher_tool as C

    r = C.run_readonly(g, "MATCH (t:Team)-[:OWNS]->(c:Component) RETURN t.name AS team, count(c) AS n "
                          "ORDER BY n DESC LIMIT 1")
    assert r["rows"] and r["columns"] == ["team", "n"]
    # A literal containing write words is fine; an actual write is not.
    assert C.run_readonly(g, "MATCH (c:Change) WHERE c.summary = 'Create SET DELETE' RETURN count(c) AS n")
    for bad in ("CREATE (:X)", "MATCH (n) DETACH DELETE n", "MATCH (c:Component) SET c.x = 1"):
        with _pt.raises(C.CypherRejected):
            C.run_readonly(g, bad)
    # Even if the pre-check is bypassed, FalkorDB refuses the write.
    with _pt.raises(Exception):
        g.ro_query("CREATE (:Leak)")
    assert not rows(g, "MATCH (n:X) RETURN n") and not rows(g, "MATCH (n:Leak) RETURN n")


def test_schema_includes_edge_properties(g):
    from firebreak import cypher_tool as C

    s = C.schema(g)
    assert "Component" in s["labels"] and "name" in s["labels"]["Component"]
    assert "gmv_per_hour_usd" in s["relationship_properties"]["USES"]
    assert "mode" in s["relationship_properties"]["DEPENDS_ON"]
