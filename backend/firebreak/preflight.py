"""Pre-deploy risk check: ask the graph before a change ships, not after it breaks.

Same graph, same tools as incident response, pointed at the future:
  - blast radius and customers/GMV exposed if this component fails
  - how central it is (FalkorDB betweenness: is it a choke point?)
  - what broke the last times someone changed it, and what fixed it
  - recent changes already in flight on the same dependency paths
  - who should review: people with real history on this component, not just the owner

The score is transparent: every factor is listed with its contribution.
"""

import time

from falkordb import Graph

from . import graph_algos
from . import tools as T
from .db import rows
from .simulator import now_ms

KIND_RISK = {"migration": 1.0, "config": 0.7, "flag": 0.6, "deploy": 0.5}
RECENT_WINDOW_MS = 24 * 3_600_000

PAST_INCIDENTS = """
MATCH (i:Incident)-[:ROOT_CAUSE]->(rc)
OPTIONAL MATCH (rc)-[:CHANGED]->(cc:Component)
WITH i, rc, coalesce(cc.name, rc.name) AS comp
WHERE comp = $name
OPTIONAL MATCH (i)-[:MITIGATED_BY]->(a:Action) WHERE a.status = 'executed' AND a.kind <> 'page'
OPTIONAL MATCH (pm:Postmortem)-[:DOCUMENTS]->(i)
RETURN i.id AS id, i.title AS title, i.severity AS severity, rc.kind AS change_kind,
       collect(DISTINCT a.kind) AS fixes, i.started_at AS started_at, i.mitigated_at AS mitigated_at,
       pm.id AS postmortem
ORDER BY started_at DESC
"""

IN_FLIGHT = """
MATCH (root:Component {name: $name})
MATCH (other:Component)
WHERE other <> root AND ((other)-[:DEPENDS_ON*1..4]->(root) OR (root)-[:DEPENDS_ON*1..4]->(other))
MATCH (ch:Change)-[:CHANGED]->(other)
WHERE ch.ts >= $since AND ch.reverted_at IS NULL
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(ch)
RETURN ch.id AS id, other.name AS component, ch.kind AS kind, ch.summary AS summary, p.name AS author, ch.ts AS ts
ORDER BY ts DESC LIMIT 5
"""

RELATED_DECISIONS = """
MATCH (d:Decision)-[:ABOUT]->(:Component {name: $name})
OPTIONAL MATCH (p:Person)-[:DECIDED]->(d)
RETURN d.id AS id, d.title AS title, d.consequences AS consequences, collect(p.name) AS decided_by
"""


def check(g: Graph, component: str, kind: str = "deploy", author: str | None = None) -> dict:
    t0 = time.perf_counter()
    exists = rows(g, "MATCH (c:Component {name: $n}) RETURN c.tier AS tier, c.kind AS ckind", {"n": component})
    if not exists:
        raise KeyError(component)
    tier = exists[0]["tier"] or 3

    blast = T.blast_radius(g, component).data
    impact = T.business_impact(g, component).data
    gmv = sum(c["gmv_per_hour"] or 0 for c in impact)
    bw = graph_algos.betweenness(g)
    bw_norm = bw.normalized().get(component, 0.0)
    past = rows(g, PAST_INCIDENTS, {"name": component})
    in_flight = rows(g, IN_FLIGHT, {"name": component, "since": now_ms() - RECENT_WINDOW_MS})
    decisions = rows(g, RELATED_DECISIONS, {"name": component})
    reviewers = [r for r in T.who_knows(g, component, top=4).data if r["id"] != author][:3]
    owners = T.owners_and_oncall(g, component, now_ms()).data

    for p in past:
        p["ttm_min"] = (round((p["mitigated_at"] - p["started_at"]) / 60_000)
                        if p["mitigated_at"] and p["started_at"] else None)
    same_kind = [p for p in past if p["change_kind"] == kind]

    # Every factor is in [0, 1] and listed, so the score is auditable.
    max_blast = rows(g, "MATCH (c:Component) RETURN count(c) AS n")[0]["n"] or 1
    factors = {
        "blast_radius": round(min(1.0, len(blast) / (max_blast * 0.3)), 3),
        "customer_exposure": round(min(1.0, gmv / 100_000), 3),
        "choke_point": round(bw_norm, 3),
        "incident_history": round(min(1.0, len(past) / 3), 3),
        "same_kind_broke_before": 1.0 if same_kind else 0.0,
        "change_kind": KIND_RISK.get(kind, 0.5),
        "tier": round((4 - tier) / 3, 3),
        "concurrent_changes": round(min(1.0, len(in_flight) / 3), 3),
    }
    weights = {"blast_radius": 0.18, "customer_exposure": 0.18, "choke_point": 0.12, "incident_history": 0.14,
               "same_kind_broke_before": 0.12, "change_kind": 0.10, "tier": 0.08, "concurrent_changes": 0.08}
    score = round(sum(factors[k] * weights[k] for k in weights), 3)
    level = "high" if score >= 0.55 else "medium" if score >= 0.3 else "low"

    advice = []
    if same_kind:
        p = same_kind[0]
        advice.append(f"A {kind} here caused {p['id']} ({p['title']}); "
                      f"{'/'.join(p['fixes']) or 'manual fix'} resolved it"
                      + (f" in {p['ttm_min']} min" if p["ttm_min"] is not None else "") + ".")
    if bw_norm >= 0.5:
        advice.append(f"{component} is a choke point (betweenness rank top "
                      f"{1 + sorted(bw.scores.values(), reverse=True).index(bw.scores.get(component, 0))}); "
                      "ship off-peak with a rollback ready.")
    if in_flight:
        advice.append(f"{len(in_flight)} other change(s) in the last 24h on connected components "
                      f"({', '.join(c['id'] for c in in_flight[:3])}); avoid stacking deploys.")
    if decisions:
        advice.append(f"Read {decisions[0]['id']} first: {decisions[0]['consequences']}")
    if level == "high" and reviewers:
        advice.append(f"Get a review from {reviewers[0]['name']} ({reviewers[0]['reasons'][0]}).")

    return {
        "component": component, "kind": kind, "risk": level, "score": score,
        "factors": factors, "weights": weights,
        "blast_radius": blast, "customers": impact, "gmv_per_hour": gmv,
        "betweenness": round(bw.scores.get(component, 0.0), 2),
        "past_incidents": past[:5], "in_flight": in_flight, "decisions": decisions,
        "reviewers": reviewers, "owners": owners, "advice": advice,
        "cypher": [PAST_INCIDENTS.strip(), IN_FLIGHT.strip(), bw.cypher],
        "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
