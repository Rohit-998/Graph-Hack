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

from . import embeddings, memory
from . import tools as T
from .db import rows
from .llm import gateway
from .incidents import alerting_components, set_status
from .simulator import now_ms

MODEL = "deterministic"
_seq = itertools.count(1)

REMEDIATION = {"deploy": "rollback", "config": "rollback", "migration": "rollback", "flag": "flag_off"}


# --- Blackboard writes -------------------------------------------------------------

def record_step(g: Graph, incident_id: str, agent: str, tool: str, cypher: str, summary: str,
                duration_ms: float, touched: list[str] | None = None, model: str = None) -> str:
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
         "dur": round(duration_ms, 2), "model": model or MODEL, "ts": now_ms(), "touched": touched or []},
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

    # Historian behaviour: recall similar past incidents (vector + structural overlap).
    t_sim = time.perf_counter()
    started = rows(g, "MATCH (i:Incident {id: $iid}) RETURN i.title AS t, i.started_at AS s", {"iid": iid})[0]
    query_text = embeddings.incident_text(started["t"], f"{top['statement']}. {top['change_summary'] or ''}",
                                          alerting + [component])
    similar, sim_cypher = await asyncio.to_thread(memory.similar_incidents, g, iid, alerting + [component], query_text)
    seen = next((s for s in similar if s["rc_component"] == component), None)
    record_step(
        g, iid, "commander", "similar_incidents", sim_cypher,
        (f"Seen before: {seen['id']} \"{seen['title']}\" (similarity {seen['score']:.2f}); "
         f"{'/'.join(seen['actions']) or 'manual fix'} resolved it in {seen['ttm_min']} min")
        if seen else
        (f"Closest past incidents: {', '.join(s['id'] for s in similar)}; none rooted on {component}"
         if similar else "No similar past incidents"),
        (time.perf_counter() - t_sim) * 1000, [component],
    )

    # Verdict. Memory corroboration closes part of the remaining doubt; shown as its own bar.
    conf = top["confidence"]
    breakdown = json.loads(top["breakdown"]) if top["breakdown"] else {}
    if seen:
        boost = round((1 - conf) * 0.5 * seen["score"], 4)
        conf = round(conf + boost, 4)
        breakdown["memory"] = boost
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

    # Procedural memory: cite the playbook's track record for this fix on this component.
    pb = next((p for p in memory.playbook_stats(g, component) if p["kind"] == kind), None)
    track = f" (playbook: {pb['success']}/{pb['success'] + pb['failure']} past successes)" if pb else ""
    actions = [{"kind": kind, "target": component,
                "reason": f"{kind} {top['change'] if is_change else component} to clear the fault{track}"}]
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

    # Optional LLM narrative (lean mode: the only LLM call per incident). The verdict above is
    # already decided by the graph; the narrative is validated to reference it, else discarded.
    facts = {
        "verdict": headline, "root_cause_id": top["change"] if is_change else component, "component": component,
        "change_summary": top["change_summary"], "evidence_path": evidence, "alerting": alerting,
        "rejected_decoys": [h["statement"] for h in rows(g, """
            MATCH (:Incident {id: $iid})-[:HAS_HYPOTHESIS]->(h:Hypothesis {status: 'rejected'})
            RETURN h.statement AS statement""", {"iid": iid})],
        "customers": [c["customer"] for c in impact.data], "gmv_per_hour": gmv,
        "seen_before": seen and {k: seen[k] for k in ("id", "title", "actions", "ttm_min")},
        "proposed": [a["reason"] for a in actions],
    }
    t_llm = time.perf_counter()
    narrative = await asyncio.to_thread(gateway.chat, NARRATIVE_SYSTEM, json.dumps(facts), max_tokens=220)
    if narrative and facts["root_cause_id"] not in narrative:
        narrative = None  # guardrail: must cite the graph-chosen root cause
    narrative_model = gateway.model if narrative else MODEL
    narrative = narrative or _template_narrative(facts)
    record_step(g, iid, "commander", "narrate", "", narrative, (time.perf_counter() - t_llm) * 1000,
                model=narrative_model)

    ttrc = now_ms()
    g.query(
        """
        MATCH (i:Incident {id: $iid})
        SET i.summary = $summary, i.narrative = $narrative, i.confidence = $conf, i.breakdown = $breakdown,
            i.evidence_path = $path, i.impact = $impact, i.responders = $team, i.ttrc_ms = $ttrc - i.started_at,
            i.seen_before = $seen, i.similar = $similar
        """,
        {"iid": iid, "summary": headline, "narrative": narrative, "conf": conf, "breakdown": json.dumps(breakdown),
         "path": json.dumps(evidence), "team": json.dumps(team), "ttrc": ttrc,
         "seen": seen["id"] if seen else None, "similar": json.dumps(similar),
         "impact": json.dumps({"customers": impact.data, "gmv_per_hour": gmv, "blast_radius": blast.data})},
    )
    g.query("MATCH (i:Incident {id: $iid})-[r:ROOT_CAUSE]->() SET r.confidence = $conf", {"iid": iid, "conf": conf})
    set_status(g, iid, "identified", ttrc)
    await asyncio.to_thread(memory.embed_incidents, g, [iid])
    record_step(g, iid, "commander", "verdict", rc_cypher.strip(),
                f"{headline}. Proposed: {', '.join(a['kind'] for a in actions)} (awaiting approval)",
                (time.perf_counter() - t0) * 1000, evidence)
    return {"incident": iid, "headline": headline, "root_cause": top["change"] if is_change else component,
            "component": component, "confidence": conf, "evidence_path": evidence, "narrative": narrative,
            "narrative_model": narrative_model, "seen_before": seen and seen["id"], "similar": similar,
            "actions": actions, "team": team, "duration_s": round(time.perf_counter() - t0, 3)}


NARRATIVE_SYSTEM = (
    "You are the incident Commander. In 2-3 plain sentences for an on-call engineer, explain the verdict "
    "using only the JSON facts: what broke, how it reached the alerting services (evidence path), why any "
    "rejected decoy was ruled out, and what to do next. Always include root_cause_id verbatim. No markdown."
)


def _template_narrative(f: dict) -> str:
    s = (f"{f['verdict']}. The fault travels {' -> '.join(f['evidence_path'])}, which explains the alerts on "
         f"{', '.join(f['alerting'])}.")
    if f["rejected_decoys"]:
        s += f" Ruled out: {f['rejected_decoys'][0]}."
    if f["seen_before"]:
        sb = f["seen_before"]
        s += f" Seen before in {sb['id']} ({sb['title']}), fixed by {'/'.join(sb['actions']) or 'hand'} in {sb['ttm_min']} min."
    return s + f" Next: {f['proposed'][0]}."
