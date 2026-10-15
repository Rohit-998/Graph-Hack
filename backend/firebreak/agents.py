"""The agent team (PRD §10): Commander, Detective, Responder.

Agents never read each other's prompts or return values to coordinate. Detective
and Responder write Hypothesis / AgentStep nodes to the graph; Commander reads
the blackboard back from FalkorDB and decides.

v1 runs deterministically (LLM_PROVIDER=none): the graph engines produce the
answer and narrative comes from templates.
"""

import asyncio
import itertools
import json
import time

from falkordb import Graph

from . import tools as T
from .db import rows
from .incidents import alerting_components, set_status
from .simulator import now_ms

MODEL = "deterministic"
_seq = itertools.count(1)

REMEDIATION = {"deploy": "rollback", "config": "rollback", "migration": "rollback", "flag": "flag_off"}


# --- Blackboard writes -------------------------------------------------------------

def record_step(g: Graph, incident_id: str, agent: str, tool: str, cypher: str, summary: str,
                duration_ms: float, touched: list[str] | None = None) -> str:
    sid = f"STEP-{incident_id}-{now_ms()}-{next(_seq)}"
    g.query(
        """
        MATCH (i:Incident {id: $iid})
        CREATE (i)-[:HAS_STEP]->(s:AgentStep {id: $sid, agent: $agent, tool: $tool, cypher: $query_text,
                                              summary: $summary, duration_ms: $dur, model: $model, ts: $ts})
        WITH i, s
        OPTIONAL MATCH (i)-[:HAS_STEP]->(prev:AgentStep {agent: $agent})
        WHERE prev.id <> s.id AND NOT (prev)-[:NEXT]->()
        FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | CREATE (prev)-[:NEXT]->(s))
        WITH s
        UNWIND $touched AS name
        MATCH (c:Component {name: name})
        CREATE (s)-[:TOUCHED]->(c)
        """,
        {"iid": incident_id, "sid": sid, "agent": agent, "tool": tool, "query_text": cypher, "summary": summary,
         "dur": round(duration_ms, 2), "model": MODEL, "ts": now_ms(), "touched": touched or []},
    )
    return sid


def _step(g: Graph, iid: str, agent: str, res: T.ToolResult, summary: str, touched: list[str] | None = None):
    record_step(g, iid, agent, res.tool, res.cypher, summary, res.duration_ms, touched)


# --- Detective ---------------------------------------------------------------------

def detective(g: Graph, iid: str) -> None:
    alerting = alerting_components(g, iid)
    ranked, rejected, calls = T.rank_root_causes(g, alerting, now_ms())
    cov, chg, _hist, _crit = calls
    _step(g, iid, "detective", cov,
          f"Traced DEPENDS_ON from {len(alerting)} alerting services; {len(cov.data)} components in the closure",
          alerting)
    _step(g, iid, "detective", chg, f"Found {len(chg.data)} changes in the last 2h")

    hyps = []
    for r in ranked[:5]:
        if not r.has_evidence:
            continue
        what = f"{r.top_change.kind} {r.top_change.id} on {r.component}" if r.top_change else f"{r.component} itself"
        hyps.append({
            "id": f"HYP-{iid}-{len(hyps) + 1}", "statement": f"Root cause is {what}",
            "confidence": round(r.confidence, 4), "status": "proposed", "breakdown": json.dumps(r.breakdown),
            "change": r.top_change.id if r.top_change else None, "component": r.component,
            "coverage": r.coverage,
        })
    # Decoys: recent changes no alert depends on. Recorded as rejected, with the reason.
    for ch in rejected:
        hyps.append({
            "id": f"HYP-{iid}-{len(hyps) + 1}",
            "statement": f"{ch['change_kind']} {ch['change']} on {ch['component']} explains 0/{len(alerting)} alerts",
            "confidence": 0.0, "status": "rejected", "breakdown": json.dumps({"coverage": 0.0}),
            "change": ch["change"], "component": ch["component"], "coverage": 0.0,
        })

    g.query(
        """
        MATCH (i:Incident {id: $iid})
        UNWIND $hyps AS h
        CREATE (i)-[:HAS_HYPOTHESIS]->(x:Hypothesis {id: h.id, statement: h.statement, confidence: h.confidence,
                                                      status: h.status, proposed_by: 'detective',
                                                      breakdown: h.breakdown, coverage: h.coverage})
        WITH x, h
        OPTIONAL MATCH (ch:Change {id: h.change})
        OPTIONAL MATCH (c:Component {name: h.component})
        FOREACH (_ IN CASE WHEN ch IS NULL THEN [1] ELSE [] END | CREATE (x)-[:SUSPECTS]->(c))
        FOREACH (_ IN CASE WHEN ch IS NULL THEN [] ELSE [1] END | CREATE (x)-[:SUSPECTS]->(ch))
        """,
        {"iid": iid, "hyps": hyps},
    )
    top = next((h for h in hyps if h["status"] == "proposed"), None)
    n_rej = sum(1 for h in hyps if h["status"] == "rejected")
    record_step(g, iid, "detective", "write_hypotheses", "CREATE (:Hypothesis)",
                f"Top suspect: {top['statement']} ({top['confidence']:.0%}). Rejected {n_rej} decoy change(s)."
                if top else "No candidate with direct evidence", 0, [top["component"]] if top else [])


# --- Responder ---------------------------------------------------------------------

def responder(g: Graph, iid: str) -> None:
    """Works out who should act. Reads the Detective's top hypothesis from the graph
    if it is already there; otherwise starts from the alerting services' owners."""
    alerting = alerting_components(g, iid)
    owners = []
    for comp in alerting:
        res = T.owners_and_oncall(g, comp, now_ms())
        owners += [dict(r, component=comp) for r in res.data]
        _step(g, iid, "responder", res,
              f"{comp} is owned by {res.data[0]['team'] if res.data else 'nobody'}; "
              f"on-call {', '.join(r['on_call'] for r in res.data if r['on_call']) or 'none'}", [comp])
    g.query("MATCH (i:Incident {id: $iid}) SET i.symptom_owners = $o",
            {"iid": iid, "o": json.dumps(owners)})


def responder_for_suspect(g: Graph, iid: str, component: str, author_name: str | None) -> dict:
    res = T.owners_and_oncall(g, component, now_ms())
    _step(g, iid, "responder", res,
          f"Suspect {component} is owned by {res.data[0]['team'] if res.data else 'nobody'}", [component])
    experts = T.who_knows(g, component)
    _step(g, iid, "responder", experts,
          "Experts: " + ", ".join(f"{e['name']} ({e['score']})" for e in experts.data), [component])
    primary = next((r for r in res.data if r["level"] == 1), res.data[0] if res.data else None)
    return {
        "team": primary["team"] if primary else None,
        "channel": primary["channel"] if primary else None,
        "on_call": [{"id": r["id"], "name": r["on_call"], "level": r["level"]} for r in res.data if r["on_call"]],
        "escalation": primary["escalation"] if primary else [],
        "experts": experts.data,
        "author": author_name,
    }


# --- Commander ---------------------------------------------------------------------

def _read_blackboard(g: Graph, iid: str) -> list[dict]:
    return rows(g, """
        MATCH (:Incident {id: $iid})-[:HAS_HYPOTHESIS]->(h:Hypothesis {status: 'proposed'})-[:SUSPECTS]->(s)
        OPTIONAL MATCH (s)-[:CHANGED]->(c:Component)
        OPTIONAL MATCH (p:Person)-[:AUTHORED]->(s)
        RETURN h.id AS id, h.statement AS statement, h.confidence AS confidence, h.breakdown AS breakdown,
               s.id AS change, s.kind AS change_kind, s.summary AS change_summary,
               coalesce(c.name, s.name) AS component, s.kind AS component_kind, p.id AS author_id,
               p.name AS author, labels(s) AS labels
        ORDER BY h.confidence DESC
    """, {"iid": iid})


async def investigate(g: Graph, iid: str) -> dict:
    t0 = time.perf_counter()
    # Re-investigation replaces the previous blackboard and proposals.
    g.query("""
        MATCH (i:Incident {id: $iid})
        OPTIONAL MATCH (i)-[:HAS_HYPOTHESIS]->(h) DETACH DELETE h
        WITH i OPTIONAL MATCH (i)-[:HAS_STEP]->(s) DETACH DELETE s
        WITH i OPTIONAL MATCH (i)-[:MITIGATED_BY]->(a:Action {status: 'proposed'}) DETACH DELETE a
        WITH i OPTIONAL MATCH (i)-[r:ROOT_CAUSE]->() DELETE r
    """, {"iid": iid})
    alerting = alerting_components(g, iid)
    record_step(g, iid, "commander", "open_incident", "MATCH (i:Incident)-[:TRIGGERED_BY]->(:Alert)",
                f"Incident {iid}: {len(alerting)} alerting services. Dispatching Detective and Responder.", 0,
                alerting)

    # Parallel dispatch. Each agent writes to the graph; nothing is returned for coordination.
    await asyncio.gather(asyncio.to_thread(detective, g, iid), asyncio.to_thread(responder, g, iid))

    board = _read_blackboard(g, iid)
    if not board:
        record_step(g, iid, "commander", "verdict", "", "No hypothesis with evidence. Escalating to humans.", 0)
        return {"incident": iid, "root_cause": None}
    top = board[0]
    is_change = "Change" in top["labels"]
    component = top["component"]

    # Evidence path from the alert closest to the cause.
    paths = [T.evidence_path(g, a, component) for a in alerting]
    best = min((p for p in paths if p.data), key=lambda p: p.data[0]["hops"], default=None)
    evidence = best.data[0]["path"] if best else [component]
    if best:
        _step(g, iid, "commander", best, f"Evidence path: {' -> '.join(evidence)}", evidence)

    blast = T.blast_radius(g, component)
    impact = T.business_impact(g, component)
    gmv = sum(c["gmv_per_hour"] or 0 for c in impact.data)
    _step(g, iid, "commander", blast, f"Blast radius of {component}: {len(blast.data)} upstream components",
          [b["component"] for b in blast.data])
    _step(g, iid, "commander", impact,
          f"{len(impact.data)} customers exposed, ${gmv:,.0f}/hr GMV at risk")

    team = await asyncio.to_thread(responder_for_suspect, g, iid, component, top["author"])

    # Verdict
    conf = top["confidence"]
    rc_cypher = """
        MATCH (i:Incident {id: $iid}) MATCH (x) WHERE (x:Change AND x.id = $change) OR (x:Component AND x.name = $comp)
        WITH i, x LIMIT 1 CREATE (i)-[:ROOT_CAUSE {confidence: $conf}]->(x)
    """
    g.query(rc_cypher, {"iid": iid, "change": top["change"] if is_change else None, "comp": component, "conf": conf})
    g.query("MATCH (:Incident {id: $iid})-[:HAS_HYPOTHESIS]->(h:Hypothesis {id: $hid}) SET h.status = 'accepted'",
            {"iid": iid, "hid": top["id"]})

    if is_change:
        headline = (f"Root cause: {top['change_kind']} {top['change']} to {component}"
                    f"{' by ' + top['author'] if top['author'] else ''} ({conf:.0%} confidence)")
        kind = REMEDIATION.get(top["change_kind"], "rollback")
    else:
        headline = f"Root cause: {component} is degraded ({conf:.0%} confidence)"
        failover = rows(g, "MATCH (:Component {name: $c})-[:FAILS_OVER_TO]->(b) RETURN b.name AS b", {"c": component})
        kind = "failover" if failover else "page"

    actions = [{"kind": kind, "target": component,
                "reason": f"{kind} {top['change'] if is_change else component} to clear the fault"}]
    page_ids = list(dict.fromkeys(
        ([top["author_id"]] if top["author_id"] else []) + [p["id"] for p in team["on_call"] if p["level"] == 1]
    ))
    if page_ids:
        actions.append({"kind": "page", "target": ",".join(page_ids),
                        "reason": f"Page {', '.join(page_ids)} on {team['channel']}"})
    for n, a in enumerate(actions, 1):
        a["id"] = f"ACT-{iid}-{n}"
    g.query(
        """
        MATCH (i:Incident {id: $iid})
        UNWIND $actions AS a
        CREATE (i)-[:MITIGATED_BY]->(:Action {id: a.id, kind: a.kind, target: a.target, reason: a.reason,
                                              status: 'proposed', proposed_by: 'commander'})
        """,
        {"iid": iid, "actions": actions},
    )

    ttrc = now_ms()
    g.query(
        """
        MATCH (i:Incident {id: $iid})
        SET i.summary = $summary, i.confidence = $conf, i.breakdown = $breakdown,
            i.evidence_path = $path, i.impact = $impact, i.responders = $team
        """,
        {"iid": iid, "summary": headline, "conf": conf, "breakdown": top["breakdown"],
         "path": json.dumps(evidence), "team": json.dumps(team),
         "impact": json.dumps({"customers": impact.data, "gmv_per_hour": gmv, "blast_radius": blast.data})},
    )
    set_status(g, iid, "identified", ttrc)
    record_step(g, iid, "commander", "verdict", rc_cypher.strip(),
                f"{headline}. Proposed: {', '.join(a['kind'] for a in actions)} (awaiting approval)",
                (time.perf_counter() - t0) * 1000, evidence)
    return {"incident": iid, "headline": headline, "root_cause": top["change"] if is_change else component,
            "component": component, "confidence": conf, "evidence_path": evidence,
            "actions": actions, "team": team, "duration_s": round(time.perf_counter() - t0, 3)}
