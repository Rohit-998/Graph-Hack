"""Graph tools: every agent capability is a Cypher query against FalkorDB (PRD §9).

Each tool returns plain dicts and the Cypher it ran, so agent steps can record
exactly what was asked of the graph.
"""

import time
from dataclasses import dataclass

from falkordb import Graph

from .db import rows
from .rca import CandidateFacts, ChangeFact, Ranked, rank


@dataclass
class ToolResult:
    tool: str
    cypher: str
    data: object
    duration_ms: float


def _run(g: Graph, tool: str, cypher: str, params: dict | None = None) -> ToolResult:
    t0 = time.perf_counter()
    data = rows(g, cypher, params)
    return ToolResult(tool, cypher.strip(), data, (time.perf_counter() - t0) * 1000)


# --- §9.1 Blast radius -------------------------------------------------------

BLAST_RADIUS = """
MATCH (root:Component {name: $name})
MATCH p = (up:Component)-[:DEPENDS_ON*1..6]->(root)
WITH up, p, all(r IN relationships(p) WHERE r.mode = 'sync') AS hard
WITH up, min(length(p)) AS hops, max(CASE WHEN hard THEN 1 ELSE 0 END) AS anyHard
RETURN up.name AS component, up.tier AS tier, hops,
       CASE WHEN anyHard = 1 THEN 'down' ELSE 'degraded' END AS impact
ORDER BY hops, tier
"""


def blast_radius(g: Graph, name: str) -> ToolResult:
    return _run(g, "blast_radius", BLAST_RADIUS, {"name": name})


# --- §9.2 Business impact ------------------------------------------------------

BUSINESS_IMPACT = """
MATCH (root:Component {name: $name})
MATCH (entry:Component)-[:DEPENDS_ON*0..6]->(root)
MATCH (prod:Product)-[:SERVED_BY]->(entry)
WITH DISTINCT prod
MATCH (c:Customer)-[u:USES]->(prod)
RETURN c.id AS id, c.name AS customer, c.tier AS tier, c.sla_target AS sla,
       collect(prod.name) AS products, sum(u.gmv_per_hour_usd) AS gmv_per_hour
ORDER BY gmv_per_hour DESC
"""


def business_impact(g: Graph, name: str) -> ToolResult:
    return _run(g, "business_impact", BUSINESS_IMPACT, {"name": name})


# --- §9.3 Root-cause candidates ------------------------------------------------

RCA_COVERAGE = """
UNWIND $alerting AS a
MATCH (s:Component {name: a})
MATCH p = (s)-[:DEPENDS_ON*0..6]->(c:Component)
WITH c, a, min(length(p)) AS hops
WITH c, collect({alert: a, hops: hops}) AS explains
RETURN c.name AS candidate, c.kind AS kind, c.status AS status, explains
"""

RCA_CHANGES = """
MATCH (ch:Change)-[:CHANGED]->(c:Component)
WHERE ch.ts >= $since AND ch.ts <= $until
OPTIONAL MATCH (author:Person)-[:AUTHORED]->(ch)
RETURN c.name AS component, c.kind AS kind, c.status AS status, ch.id AS change, ch.kind AS change_kind,
       ch.summary AS summary, ch.risk AS risk, ch.ts AS ts, author.name AS author
ORDER BY ch.ts DESC
"""

# Share of past incidents rooted on a component (directly or via a change on it).
RCA_HISTORY = """
MATCH (i:Incident {status: 'resolved'})-[:ROOT_CAUSE]->(rc)
OPTIONAL MATCH (rc)-[:CHANGED]->(cc:Component)
WITH coalesce(cc.name, rc.name) AS component, count(i) AS n
RETURN component, n
"""

# Reverse-dependency fan-in as a criticality proxy: how many components depend on c.
RCA_CRITICALITY = """
MATCH (c:Component)
OPTIONAL MATCH (up:Component)-[:DEPENDS_ON*1..6]->(c)
RETURN c.name AS component, count(DISTINCT up) AS dependents
"""


def rank_root_causes(
    g: Graph, alerting: list[str], now_ms: int, window_ms: int = 2 * 3_600_000
) -> tuple[list[Ranked], list[dict], list[ToolResult]]:
    """Returns (ranked candidates, changes outside the alert closure, tool calls)."""
    cov = _run(g, "rca_coverage", RCA_COVERAGE, {"alerting": alerting})
    chg = _run(g, "rca_changes", RCA_CHANGES, {"since": now_ms - window_ms, "until": now_ms})
    hist = _run(g, "rca_history", RCA_HISTORY)
    crit = _run(g, "rca_criticality", RCA_CRITICALITY)

    total_hist = sum(r["n"] for r in hist.data) or 1
    history = {r["component"]: r["n"] / total_hist for r in hist.data}
    max_dep = max((r["dependents"] for r in crit.data), default=0) or 1
    criticality = {r["component"]: r["dependents"] / max_dep for r in crit.data}

    changes_by_comp: dict[str, list[ChangeFact]] = {}
    for r in chg.data:
        changes_by_comp.setdefault(r["component"], []).append(
            ChangeFact(r["change"], r["component"], r["change_kind"], r["summary"], r["risk"], r["ts"], r["author"])
        )

    covered = {r["candidate"] for r in cov.data}
    candidates = [
        CandidateFacts(
            component=r["candidate"], explains=r["explains"], kind=r["kind"],
            degraded=r["status"] != "healthy", criticality=criticality.get(r["candidate"], 0.0),
            history_prior=history.get(r["candidate"], 0.0), changes=changes_by_comp.get(r["candidate"], []),
        )
        for r in cov.data
    ]
    # Components with recent changes but outside every alert's dependency closure:
    # these are the decoys. They enter ranking with coverage 0 so the rejection is visible.
    rejected = [r for r in chg.data if r["component"] not in covered]
    for comp in {r["component"] for r in rejected}:
        candidates.append(CandidateFacts(
            component=comp, explains=[], kind=next(r["kind"] for r in rejected if r["component"] == comp),
            criticality=criticality.get(comp, 0.0), changes=changes_by_comp[comp],
        ))

    return rank(candidates, len(alerting), now_ms), rejected, [cov, chg, hist, crit]


# --- §9.3 step 4 Evidence path ---------------------------------------------------

EVIDENCE_PATH = """
MATCH (a:Component {name: $alerting}), (c:Component {name: $candidate})
MATCH p = (a)-[:DEPENDS_ON*0..6]->(c)
RETURN [n IN nodes(p) | n.name] AS path, length(p) AS hops
ORDER BY hops ASC LIMIT 1
"""


def evidence_path(g: Graph, alerting: str, candidate: str) -> ToolResult:
    return _run(g, "evidence_path", EVIDENCE_PATH, {"alerting": alerting, "candidate": candidate})


# --- §9.4 Who knows this system ---------------------------------------------------

WHO_KNOWS = """
MATCH (c:Component {name: $name})
OPTIONAL MATCH (p1:Person)-[:RESPONDED_TO]->(i:Incident)
  WHERE (i)-[:AFFECTED]->(c) OR (i)-[:ROOT_CAUSE]->(c) OR (i)-[:ROOT_CAUSE]->(:Change)-[:CHANGED]->(c)
WITH c, collect(DISTINCT p1.id) AS responded
OPTIONAL MATCH (p2:Person)-[:AUTHORED]->(:Change)-[:CHANGED]->(c)
WITH c, responded, collect(DISTINCT p2.id) AS authored
OPTIONAL MATCH (p3:Person)-[:WROTE]->(:Runbook)-[:COVERS]->(c)
WITH c, responded, authored, collect(DISTINCT p3.id) AS wrote
OPTIONAL MATCH (p4:Person)-[e:EXPERT_IN]->(c)
RETURN responded, authored, wrote, collect({id: p4.id, score: e.score}) AS learned
"""

PEOPLE_NAMES = "MATCH (p:Person) WHERE p.id IN $ids RETURN p.id AS id, p.name AS name, p.title AS title"


def who_knows(g: Graph, name: str, top: int = 3) -> ToolResult:
    res = _run(g, "who_knows", WHO_KNOWS, {"name": name})
    if not res.data:
        res.data = []
        return res
    r = res.data[0]
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add(pid: str | None, pts: float, why: str) -> None:
        if pid:
            scores[pid] = scores.get(pid, 0) + pts
            reasons.setdefault(pid, []).append(why)

    for pid in r["responded"]:
        add(pid, 3, f"responded to past incidents on {name}")
    for pid in r["wrote"]:
        add(pid, 2, f"wrote a runbook for {name}")
    for pid in r["authored"]:
        add(pid, 1, f"authored changes to {name}")
    for item in r["learned"]:
        if item.get("id"):
            add(item["id"], item["score"] or 0, f"expertise score {item['score']}")

    ranked = sorted(scores, key=lambda p: -scores[p])[:top]
    names = {x["id"]: x for x in rows(g, PEOPLE_NAMES, {"ids": ranked})}
    res.data = [
        {"id": p, "name": names[p]["name"], "title": names[p]["title"],
         "score": round(scores[p], 2), "reasons": reasons[p]}
        for p in ranked
    ]
    return res


# --- §9.5 On-call and escalation ----------------------------------------------------

OWNERS_AND_ONCALL = """
MATCH (c:Component {name: $name})<-[:OWNS]-(t:Team)
OPTIONAL MATCH (p:Person)-[oc:ON_CALL]->(t)
  WHERE oc.from <= $now AND oc.until > $now
OPTIONAL MATCH (p)-[:REPORTS_TO*1..2]->(mgr:Person)
RETURN t.name AS team, t.slack_channel AS channel, p.id AS id, p.name AS on_call, oc.level AS level,
       collect(DISTINCT mgr.name) AS escalation
ORDER BY level
"""


def owners_and_oncall(g: Graph, name: str, now_ms: int) -> ToolResult:
    return _run(g, "owners_and_oncall", OWNERS_AND_ONCALL, {"name": name, "now": now_ms})


# --- §9.8 Company brain retrieval -----------------------------------------------------

SEARCH_DECISIONS = """
CALL db.idx.fulltext.queryNodes('Decision', $q) YIELD node, score
OPTIONAL MATCH (node)-[:ABOUT]->(c:Component)
OPTIONAL MATCH (p:Person)-[:DECIDED]->(node)
OPTIONAL MATCH (node)-[:DISCUSSED_IN]->(t:Thread)
RETURN 'Decision' AS type, node.id AS id, node.title AS title, node.decision AS text,
       collect(DISTINCT c.name) AS components, collect(DISTINCT p.name) AS people,
       collect(DISTINCT t.id) AS threads, score
ORDER BY score DESC LIMIT 5
"""

SEARCH_DOCS = """
CALL db.idx.fulltext.queryNodes($label, $q) YIELD node, score
OPTIONAL MATCH (node)-[:COVERS|MENTIONS|AFFECTED]->(c:Component)
OPTIONAL MATCH (p:Person)-[:WROTE|POSTED|RESPONDED_TO]->(node)
RETURN $label AS type, node.id AS id, node.title AS title,
       coalesce(node.body, node.summary) AS text,
       collect(DISTINCT c.name) AS components, collect(DISTINCT p.name) AS people,
       [] AS threads, score
ORDER BY score DESC LIMIT 5
"""


def search_knowledge(g: Graph, q: str) -> ToolResult:
    t0 = time.perf_counter()
    hits = rows(g, SEARCH_DECISIONS, {"q": q})
    for label in ("Runbook", "Thread", "Incident"):
        hits += rows(g, SEARCH_DOCS, {"q": q, "label": label})
    hits.sort(key=lambda h: -h["score"])
    return ToolResult("search_knowledge", SEARCH_DECISIONS.strip(), hits, (time.perf_counter() - t0) * 1000)
