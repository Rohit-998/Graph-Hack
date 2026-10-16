"""Incident lifecycle (PRD FR-3.1, FR-5.1).

States: investigating -> identified -> mitigating -> resolved, each timestamped.
Everything is stored in the graph; `detail` reconstructs an incident from it.
"""

import json
import threading

from falkordb import Graph

from .db import rows
from .simulator import clear_fault, now_ms

CORRELATION_WINDOW_MS = 2 * 60_000


def _next_incident_id(g: Graph) -> str:
    n = rows(g, "MATCH (i:Incident) WHERE i.id STARTS WITH 'INC-' RETURN max(toInteger(substring(i.id, 4))) AS n")
    return f"INC-{(n[0]['n'] or 2200) + 1}"


def open_incident(g: Graph, ts: int | None = None) -> str | None:
    """Correlate open alerts not yet attached to an incident into one Incident.
    If an incident is already active, new alerts within the window join it."""
    ts = ts or now_ms()
    loose = rows(g, """
        MATCH (a:Alert {status: 'open'})-[:FIRED_ON]->(c:Component)
        WHERE NOT ()-[:TRIGGERED_BY]->(a)
        RETURN a.id AS id, a.ts AS ts, c.name AS component, c.tier AS tier
    """)
    if not loose:
        return None

    active = rows(g, """
        MATCH (i:Incident) WHERE i.status IN ['investigating', 'identified', 'mitigating']
        RETURN i.id AS id, i.started_at AS started ORDER BY i.started_at DESC LIMIT 1
    """)
    if active and ts - active[0]["started"] <= CORRELATION_WINDOW_MS:
        iid = active[0]["id"]
    else:
        iid = _next_incident_id(g)
        tier1 = sum(1 for a in loose if a["tier"] == 1)
        severity = "SEV1" if tier1 >= 2 else "SEV2" if tier1 == 1 else "SEV3"
        title = "Errors on " + ", ".join(sorted(a["component"] for a in loose))
        g.query(
            """
            CREATE (:Incident {id: $id, title: $title, summary: '', severity: $sev, status: 'investigating',
                               started_at: $ts})
            """,
            {"id": iid, "title": title, "sev": severity, "ts": min(a["ts"] for a in loose)},
        )
    g.query(
        """
        MATCH (i:Incident {id: $id})
        UNWIND $alerts AS aid
        MATCH (a:Alert {id: aid})-[:FIRED_ON]->(c:Component)
        CREATE (i)-[:TRIGGERED_BY]->(a)
        MERGE (i)-[:AFFECTED {impact: c.status}]->(c)
        """,
        {"id": iid, "alerts": [a["id"] for a in loose]},
    )
    return iid


def alerting_components(g: Graph, incident_id: str) -> list[str]:
    return [r["c"] for r in rows(g, """
        MATCH (:Incident {id: $id})-[:TRIGGERED_BY]->(:Alert)-[:FIRED_ON]->(c:Component)
        RETURN DISTINCT c.name AS c ORDER BY c
    """, {"id": incident_id})]


def set_status(g: Graph, incident_id: str, status: str, ts: int | None = None) -> None:
    field = {"identified": "identified_at", "mitigating": "mitigating_at", "resolved": "resolved_at"}[status]
    g.query(f"MATCH (i:Incident {{id: $id}}) SET i.status = $s, i.{field} = $ts",
            {"id": incident_id, "s": status, "ts": ts or now_ms()})


def list_incidents(g: Graph, limit: int = 30) -> list[dict]:
    return rows(g, """
        MATCH (i:Incident)
        RETURN i.id AS id, i.title AS title, i.severity AS severity, i.status AS status,
               i.started_at AS started_at, i.resolved_at AS resolved_at, i.confidence AS confidence
        ORDER BY i.started_at DESC LIMIT $limit
    """, {"limit": limit})


def detail(g: Graph, incident_id: str) -> dict | None:
    inc = rows(g, "MATCH (i:Incident {id: $id}) RETURN properties(i) AS i", {"id": incident_id})
    if not inc:
        return None
    out = dict(inc[0]["i"])
    out.pop("embedding", None)
    for key in ("breakdown", "evidence_path", "impact", "responders", "similar", "symptom_owners"):
        if isinstance(out.get(key), str):
            out[key] = json.loads(out[key])

    out["alerts"] = rows(g, """
        MATCH (:Incident {id: $id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(c:Component)
        RETURN a.id AS id, c.name AS component, a.rule AS rule, a.value AS value, a.status AS status, a.ts AS ts
        ORDER BY a.ts
    """, {"id": incident_id})
    out["hypotheses"] = rows(g, """
        MATCH (:Incident {id: $id})-[:HAS_HYPOTHESIS]->(h:Hypothesis)
        OPTIONAL MATCH (h)-[:SUSPECTS]->(s)
        RETURN h.id AS id, h.statement AS statement, h.confidence AS confidence, h.status AS status,
               h.proposed_by AS proposed_by, h.breakdown AS breakdown, s.id AS change, s.name AS component
        ORDER BY h.confidence DESC
    """, {"id": incident_id})
    for h in out["hypotheses"]:
        if h["breakdown"]:
            h["breakdown"] = json.loads(h["breakdown"])
    out["steps"] = rows(g, """
        MATCH (:Incident {id: $id})-[:HAS_STEP]->(s:AgentStep)
        RETURN s.id AS id, s.agent AS agent, s.tool AS tool, s.cypher AS cypher, s.summary AS summary,
               s.duration_ms AS duration_ms, s.model AS model, s.ts AS ts
        ORDER BY s.ts, s.id
    """, {"id": incident_id})
    out["actions"] = rows(g, """
        MATCH (:Incident {id: $id})-[:MITIGATED_BY]->(a:Action)
        RETURN a.id AS id, a.kind AS kind, a.target AS target, a.status AS status, a.reason AS reason,
               a.proposed_by AS proposed_by, a.approved_by AS approved_by, a.result AS result
        ORDER BY a.id
    """, {"id": incident_id})
    rc = rows(g, """
        MATCH (:Incident {id: $id})-[r:ROOT_CAUSE]->(x)
        OPTIONAL MATCH (x)-[:CHANGED]->(c:Component)
        OPTIONAL MATCH (p:Person)-[:AUTHORED]->(x)
        RETURN labels(x) AS labels, x.id AS id, coalesce(c.name, x.name) AS component, x.kind AS kind,
               x.summary AS summary, p.name AS author, r.confidence AS confidence
    """, {"id": incident_id})
    out["root_cause"] = rc[0] if rc else None
    pm = rows(g, "MATCH (pm:Postmortem)-[:DOCUMENTS]->(:Incident {id: $id}) RETURN pm.id AS id, pm.body AS body, "
                 "pm.model AS model", {"id": incident_id})
    out["postmortem"] = pm[0] if pm else None
    return out


# --- Actions ---------------------------------------------------------------------

def approve_action(g: Graph, action_id: str, approved_by: str = "human", background: bool = False) -> dict:
    """Human-in-the-loop: approve and execute a proposed action against the simulated control plane."""
    res = rows(g, """
        MATCH (i:Incident)-[:MITIGATED_BY]->(a:Action {id: $id})
        RETURN a.kind AS kind, a.target AS target, a.status AS status, i.id AS incident
    """, {"id": action_id})
    if not res:
        raise KeyError(action_id)
    a = res[0]
    if a["status"] != "proposed":
        raise ValueError(f"action {action_id} is {a['status']}, not proposed")

    ts = now_ms()
    g.query("MATCH (a:Action {id: $id}) SET a.status = 'approved', a.approved_by = $by, a.approved_at = $ts",
            {"id": action_id, "by": approved_by, "ts": ts})

    if a["kind"] == "page":
        result = "paged"
        g.query("MATCH (a:Action {id: $id}) SET a.status = 'executed', a.result = $r, a.executed_at = $ts",
                {"id": action_id, "r": result, "ts": ts})
        return {"action": action_id, "kind": a["kind"], "result": result, "unhealthy": {}}

    set_status(g, a["incident"], "mitigating", ts)
    unhealthy = clear_fault(g, a["target"])
    result = "success" if not unhealthy else "partial"
    g.query("MATCH (a:Action {id: $id}) SET a.status = 'executed', a.result = $r, a.executed_at = $ts",
            {"id": action_id, "r": result, "ts": now_ms()})
    if not unhealthy:
        g.query("MATCH (i:Incident {id: $id}) SET i.mitigated_at = $ts", {"id": a["incident"], "ts": now_ms()})
        set_status(g, a["incident"], "resolved")
        # Other proposed remediations are moot once the world is green; pages go out with the fix.
        g.query("""
            MATCH (:Incident {id: $id})-[:MITIGATED_BY]->(o:Action {status: 'proposed'})
            SET o.status = CASE WHEN o.kind = 'page' THEN 'executed' ELSE 'superseded' END,
                o.result = CASE WHEN o.kind = 'page' THEN 'paged' ELSE o.result END,
                o.approved_by = CASE WHEN o.kind = 'page' THEN $by ELSE o.approved_by END
        """, {"id": a["incident"], "by": approved_by})
    else:
        from .memory import reinforce_playbook
        reinforce_playbook(g, a["target"], a["kind"], success=False)
    out = {"action": action_id, "kind": a["kind"], "result": result, "unhealthy": unhealthy,
           "incident": a["incident"]}
    if not unhealthy:
        out["scribe"] = run_scribe(g, a["incident"], background)
    return out


def run_scribe(g: Graph, incident_id: str, background: bool) -> dict | str:
    """Fire-and-forget postmortem + memory update. Synchronous for the CLI and tests."""
    from .memory import scribe

    if not background:
        return scribe(g, incident_id)

    def work() -> None:
        try:
            scribe(g, incident_id)
        except Exception as exc:
            print(f"[scribe] {incident_id}: {exc!r}")

    threading.Thread(target=work, daemon=True).start()
    return "scheduled"


def reject_action(g: Graph, action_id: str, rejected_by: str = "human") -> None:
    g.query("MATCH (a:Action {id: $id, status: 'proposed'}) SET a.status = 'rejected', a.approved_by = $by",
            {"id": action_id, "by": rejected_by})
