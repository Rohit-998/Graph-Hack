"""Agent memory (PRD FR-P1.2 to P1.4).

Episodic:   every Incident carries an embedding; similar_incidents() combines
            vector similarity with structural overlap of the affected subgraph.
Procedural: Playbook nodes (one per remediation kind per component) count
            successes and failures as actions are executed.
Semantic:   EXPERT_IN scores grow for the people who resolve incidents.

The Scribe runs after an action is approved: it writes a Postmortem, links
SIMILAR_TO edges, reinforces the playbook and updates expertise.
"""

import json
import time

from falkordb import Graph

from . import embeddings
from .db import rows
from .llm import gateway

SIMILAR_K = 8
MIN_SIMILAR = 0.55


def now_ms() -> int:
    return int(time.time() * 1000)


# --- Episodic: embeddings + recall ---------------------------------------------------

def embed_incidents(g: Graph, ids: list[str] | None = None) -> int:
    """(Re)compute embeddings for incidents. With ids=None, every incident without one."""
    where = "WHERE i.id IN $ids" if ids else "WHERE i.embedding IS NULL"
    todo = rows(g, f"""
        MATCH (i:Incident) {where}
        OPTIONAL MATCH (i)-[:AFFECTED]->(c:Component)
        RETURN i.id AS id, i.title AS title, coalesce(i.summary, '') AS summary, collect(c.name) AS comps
    """, {"ids": ids or []})
    if not todo:
        return 0
    vecs = embeddings.embed([embeddings.incident_text(t["title"], t["summary"], t["comps"]) for t in todo])
    g.query(
        "UNWIND $items AS it MATCH (i:Incident {id: it.id}) SET i.embedding = vecf32(it.v)",
        {"items": [{"id": t["id"], "v": v} for t, v in zip(todo, vecs)]},
    )
    return len(todo)


SIMILAR_INCIDENTS = """
CALL db.idx.vector.queryNodes('Incident', 'embedding', $k, vecf32($vec)) YIELD node, score
WHERE node.id <> $current AND node.status = 'resolved'
OPTIONAL MATCH (node)-[:AFFECTED]->(comp:Component) WHERE comp.name IN $affected
WITH node, score, count(DISTINCT comp) AS overlap
OPTIONAL MATCH (node)-[:ROOT_CAUSE]->(rc)
OPTIONAL MATCH (rc)-[:CHANGED]->(rcc:Component)
OPTIONAL MATCH (node)-[:MITIGATED_BY]->(a:Action) WHERE a.status = 'executed' AND a.kind <> 'page'
RETURN node.id AS id, node.title AS title, node.summary AS summary, score AS distance, overlap,
       coalesce(rcc.name, rc.name) AS rc_component, rc.id AS rc_change, rc.kind AS rc_kind,
       collect(DISTINCT a.kind) AS actions,
       node.started_at AS started_at, node.mitigated_at AS mitigated_at
"""


def similar_incidents(g: Graph, incident_id: str, affected: list[str], text: str, top: int = 3) -> tuple[list[dict], str]:
    """Hybrid recall: cosine similarity of the incident text + overlap of affected components.
    FalkorDB returns cosine *distance*; similarity = 1 - distance."""
    vec = embeddings.embed([text])[0]
    res = rows(g, SIMILAR_INCIDENTS, {"k": SIMILAR_K, "vec": vec, "current": incident_id, "affected": affected})
    out = []
    for r in res:
        sim = 1 - (r["distance"] or 1)
        overlap = r["overlap"] / max(len(affected), 1)
        r["similarity"] = round(sim, 3)
        r["overlap_ratio"] = round(overlap, 3)
        r["score"] = round(0.7 * sim + 0.3 * overlap, 3)
        ttm = (r["mitigated_at"] - r["started_at"]) / 60_000 if r["mitigated_at"] and r["started_at"] else None
        r["ttm_min"] = round(ttm) if ttm is not None else None
        out.append(r)
    out.sort(key=lambda r: -r["score"])
    return [r for r in out if r["score"] >= MIN_SIMILAR][:top], SIMILAR_INCIDENTS.strip()



# --- Procedural: playbooks -------------------------------------------------------------

def playbook_stats(g: Graph, component: str) -> list[dict]:
    return rows(g, """
        MATCH (p:Playbook)-[:FOR]->(:Component {name: $c})
        RETURN p.id AS id, p.kind AS kind, p.success_count AS success, p.failure_count AS failure,
               toFloat(p.success_count) / (p.success_count + p.failure_count) AS success_rate
        ORDER BY success_rate DESC, success DESC
    """, {"c": component})


def reinforce_playbook(g: Graph, component: str, kind: str, success: bool) -> None:
    g.query(
        """
        MATCH (c:Component {name: $c})
        MERGE (p:Playbook {id: $id})
        ON CREATE SET p.kind = $kind, p.name = $name, p.success_count = 0, p.failure_count = 0
        MERGE (p)-[:FOR]->(c)
        SET p.success_count = p.success_count + $s, p.failure_count = p.failure_count + $f, p.updated_at = $ts
        """,
        {"c": component, "id": f"PB-{component}-{kind}", "kind": kind, "name": f"{kind} {component}",
         "s": 1 if success else 0, "f": 0 if success else 1, "ts": now_ms()},
    )


def seed_playbooks(g: Graph) -> None:
    """Derive playbooks from historical incidents' executed actions."""
    hist = rows(g, """
        MATCH (i:Incident {status: 'resolved'})-[:MITIGATED_BY]->(a:Action {status: 'executed'})
        WHERE a.kind <> 'page'
        OPTIONAL MATCH (i)-[:ROOT_CAUSE]->(rc) OPTIONAL MATCH (rc)-[:CHANGED]->(c:Component)
        RETURN coalesce(c.name, rc.name) AS component, a.kind AS kind, a.result AS result
    """)
    for h in hist:
        if h["component"]:
            reinforce_playbook(g, h["component"], h["kind"], h["result"] != "failed")


# --- Scribe -------------------------------------------------------------------------------

POSTMORTEM_SYSTEM = (
    "You are the Scribe for an incident response team. Write a blameless postmortem in plain text, "
    "under 120 words, with three short sections: What happened, Impact, What fixed it. Use only the "
    "facts given. Do not invent numbers, people or systems."
)


def _template_postmortem(d: dict) -> str:
    rc = d.get("root_cause") or {}
    impact = d.get("impact") or {}
    action = next((a for a in d["actions"] if a["status"] == "executed" and a["kind"] != "page"), None)
    ttm = round((d["mitigated_at"] - d["started_at"]) / 60_000) if d.get("mitigated_at") else None
    what = (f"{rc.get('kind', 'change')} {rc['id']} to {rc['component']}"
            f"{' by ' + rc['author'] if rc.get('author') else ''} ({rc.get('summary') or 'no summary'})"
            if rc.get("id") else f"{rc.get('component', 'an upstream component')} degraded")
    return (
        f"What happened: {what}. Alerts fired on {', '.join(sorted({a['component'] for a in d['alerts']}))}.\n"
        f"Impact: {len(impact.get('customers', []))} customers exposed, "
        f"${impact.get('gmv_per_hour', 0):,.0f}/hr GMV at risk.\n"
        f"What fixed it: {action['kind'] if action else 'manual intervention'} on {action['target'] if action else '?'}"
        f"{f', mitigated in {ttm} min' if ttm is not None else ''}."
    )


def scribe(g: Graph, incident_id: str) -> dict:
    """Fire-and-forget after resolution: write the postmortem and update all memory."""
    from .incidents import detail  # local import: incidents imports this module

    d = detail(g, incident_id)
    if not d or not d.get("root_cause"):
        return {"incident": incident_id, "written": False}
    rc = d["root_cause"]
    component = rc["component"]
    action = next((a for a in d["actions"] if a["status"] == "executed" and a["kind"] != "page"), None)
    success = bool(action and action["result"] == "success")

    facts = json.dumps({k: d.get(k) for k in ("id", "title", "summary", "severity", "root_cause")} | {
        "alerting": sorted({a["component"] for a in d["alerts"]}),
        "customers": [c["customer"] for c in (d.get("impact") or {}).get("customers", [])],
        "gmv_per_hour": (d.get("impact") or {}).get("gmv_per_hour"),
        "action": action and {k: action[k] for k in ("kind", "target", "result")},
        "minutes_to_mitigate": round((d["mitigated_at"] - d["started_at"]) / 60_000) if d.get("mitigated_at") else None,
    })
    body = gateway.chat(POSTMORTEM_SYSTEM, facts, max_tokens=260)
    model = gateway.model if body else "deterministic"
    body = body or _template_postmortem(d)

    pm_id = f"PM-{incident_id}"
    g.query(
        """
        MATCH (i:Incident {id: $iid})
        MERGE (pm:Postmortem {id: $pm})
        SET pm.title = $title, pm.body = $body, pm.model = $model, pm.ts = $ts
        MERGE (pm)-[:DOCUMENTS]->(i)
        SET i.summary = $summary
        """,
        {"iid": incident_id, "pm": pm_id, "title": f"Postmortem: {d['title']}", "body": body, "model": model,
         "ts": now_ms(), "summary": d["summary"] + " " + body.replace("\n", " ")[:400]},
    )
    # Responders: the people who were paged and the person who approved.
    g.query(
        """
        MATCH (i:Incident {id: $iid})
        UNWIND $people AS pid
        MATCH (p:Person {id: pid})
        MERGE (p)-[:RESPONDED_TO]->(i)
        WITH p
        MATCH (c:Component {name: $comp})
        MERGE (p)-[e:EXPERT_IN]->(c)
        ON CREATE SET e.score = 0
        SET e.score = e.score + 0.25, e.updated_at = $ts
        """,
        {"iid": incident_id, "comp": component, "ts": now_ms(),
         "people": [p for a in d["actions"] if a["kind"] == "page" and a["status"] == "executed"
                    for p in a["target"].split(",")]},
    )
    if action:
        reinforce_playbook(g, component, action["kind"], success)

    # Re-embed with the postmortem folded into the summary, then link similar incidents.
    embed_incidents(g, [incident_id])
    text = embeddings.incident_text(d["title"], d["summary"] + " " + body, [a["component"] for a in d["alerts"]])
    similar, _ = similar_incidents(g, incident_id, [a["component"] for a in d["alerts"]] + [component], text)
    g.query(
        """
        MATCH (i:Incident {id: $iid})
        UNWIND $sim AS s
        MATCH (o:Incident {id: s.id})
        MERGE (i)-[r:SIMILAR_TO]->(o) SET r.score = s.score
        """,
        {"iid": incident_id, "sim": [{"id": s["id"], "score": s["score"]} for s in similar]},
    )
    return {"incident": incident_id, "written": True, "postmortem": pm_id, "model": model,
            "similar": [s["id"] for s in similar], "playbook": action and f"PB-{component}-{action['kind']}"}


# --- Learning curve -------------------------------------------------------------------------

def learning_curve(g: Graph) -> list[dict]:
    """Per incident class (root-cause component), how fast Firebreak reached a verdict over time."""
    return rows(g, """
        MATCH (i:Incident)-[:ROOT_CAUSE]->(rc)
        WHERE i.identified_at IS NOT NULL AND i.ttrc_ms IS NOT NULL
        OPTIONAL MATCH (rc)-[:CHANGED]->(c:Component)
        RETURN i.id AS id, coalesce(c.name, rc.name) AS component, i.ttrc_ms AS ttrc_ms,
               i.confidence AS confidence, i.seen_before AS seen_before, i.started_at AS started_at
        ORDER BY i.started_at
    """)
