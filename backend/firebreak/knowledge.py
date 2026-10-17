"""Keeping the company brain current (Track 03).

ingest():  a new doc, ticket or chat message becomes a node linked into the graph. Links are
           extracted deterministically and returned, so every edge is explainable:
             - components named in the text (exact name or a recognised short name)
             - people named in the text
             - explicit references to ADR-*, INC-*, RB-*, T-* ids
           The text is immediately searchable by Ask Firebreak.

stale():   knowledge whose subject moved on without it. A runbook or decision is flagged when
           incidents rooted on a component it covers happened after it was last reviewed, or when
           a newer document references it. Each flag says why.
"""

import re
import time
import uuid

from falkordb import Graph

from . import brain
from .db import rows

KINDS = {"doc": "Doc", "ticket": "Ticket", "chat": "Thread"}
ID_REF = re.compile(r"\b(ADR-\d+|INC-\d+|RB-\d+|T-\d+|TKT-\d+|DOC-\d+)\b")
REF_LABEL = {"ADR": "Decision", "INC": "Incident", "RB": "Runbook", "T": "Thread", "TKT": "Ticket", "DOC": "Doc"}
DAY = 86_400_000


def now_ms() -> int:
    return int(time.time() * 1000)


def ensure_indexes(g: Graph) -> None:
    """Full-text indexes for ingested labels; created once, safe to call repeatedly."""
    for label in ("Doc", "Ticket"):
        try:
            g.query(f"CALL db.idx.fulltext.createNodeIndex('{label}', 'title', 'body')")
        except Exception:
            pass  # already exists
        try:
            g.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
        except Exception:
            pass


def extract(g: Graph, text: str) -> dict:
    """Entities a piece of text refers to, resolved against the graph."""
    comps = brain.mentioned_components(g, text)
    people = [r["id"] for r in rows(g, "MATCH (p:Person) RETURN p.id AS id, p.name AS name")
              if re.search(rf"\b{re.escape(r['name'])}\b", text) or re.search(rf"\b{re.escape(r['name'].split()[0])}\b", text)]
    refs = []
    for ref in dict.fromkeys(ID_REF.findall(text)):
        label = REF_LABEL[ref.split("-")[0]]
        if rows(g, f"MATCH (n:{label} {{id: $id}}) RETURN n.id AS id", {"id": ref}):
            refs.append({"id": ref, "label": label})
    return {"components": comps, "people": people, "references": refs}


def ingest(g: Graph, kind: str, title: str, body: str, author: str | None = None,
           status: str | None = None, channel: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    ensure_indexes(g)
    label = KINDS[kind]
    prefix = {"doc": "DOC", "ticket": "TKT", "chat": "T"}[kind]
    nid = f"{prefix}-{uuid.uuid4().int % 9000 + 1000}"
    ts = now_ms()
    links = extract(g, f"{title}\n{body}")

    g.query(f"""
        CREATE (n:{label} {{id: $id, title: $title, body: $body, ts: $ts, updated_at: $ts,
                           status: $status, channel: $channel, ingested: true}})
    """, {"id": nid, "title": title, "body": body, "ts": ts, "status": status, "channel": channel})
    if author:
        rel = {"doc": "WROTE", "ticket": "REPORTED", "chat": "POSTED"}[kind]
        g.query(f"MATCH (p:Person {{id: $a}}), (n:{label} {{id: $id}}) MERGE (p)-[:{rel}]->(n)",
                {"a": author, "id": nid})
    if links["components"]:
        g.query(f"""
            MATCH (n:{label} {{id: $id}})
            UNWIND $names AS name MATCH (c:Component {{name: name}}) MERGE (n)-[:MENTIONS]->(c)
        """, {"id": nid, "names": links["components"]})
    if links["people"]:
        g.query(f"""
            MATCH (n:{label} {{id: $id}})
            UNWIND $ids AS pid MATCH (p:Person {{id: pid}}) MERGE (n)-[:MENTIONS_PERSON]->(p)
        """, {"id": nid, "ids": [p for p in links["people"] if p != author]})
    for ref in links["references"]:
        g.query(f"""
            MATCH (n:{label} {{id: $id}}), (r:{ref['label']} {{id: $ref}}) MERGE (n)-[:REFERENCES]->(r)
        """, {"id": nid, "ref": ref["id"]})
    return {"id": nid, "label": label, "links": links}


def stale(g: Graph, now: int | None = None) -> list[dict]:
    """Runbooks and decisions that their subject has outgrown, each with the reason."""
    now = now or now_ms()
    out = []
    # Runbooks: incidents rooted on a covered component after the runbook was last reviewed.
    for r in rows(g, """
        MATCH (rb:Runbook)-[:COVERS]->(c:Component)
        MATCH (i:Incident)-[:ROOT_CAUSE]->(rc)
        OPTIONAL MATCH (rc)-[:CHANGED]->(cc:Component)
        WITH rb, c, i, coalesce(cc.name, rc.name) AS rcomp
        WHERE rcomp = c.name AND i.started_at > coalesce(rb.updated_at, 0)
        OPTIONAL MATCH (p:Person)-[:WROTE]->(rb)
        RETURN rb.id AS id, rb.title AS title, rb.updated_at AS reviewed, p.name AS owner,
               collect(DISTINCT i.id) AS incidents, collect(DISTINCT c.name) AS components
    """):
        out.append({"id": r["id"], "type": "Runbook", "title": r["title"], "owner": r["owner"],
                    "reviewed_days_ago": round((now - (r["reviewed"] or 0)) / DAY) if r["reviewed"] else None,
                    "reason": f"{len(r['incidents'])} incident(s) on {', '.join(r['components'])} since last review: "
                              + ", ".join(r["incidents"][:4]),
                    "evidence": r["incidents"]})
    # Decisions: newer docs, tickets or chats that reference them (the discussion moved on).
    for r in rows(g, """
        MATCH (n)-[:REFERENCES]->(d:Decision)
        WHERE (n:Doc OR n:Ticket OR n:Thread) AND n.ts > coalesce(d.date, 0)
        OPTIONAL MATCH (p:Person)-[:DECIDED]->(d)
        RETURN d.id AS id, d.title AS title, collect(DISTINCT n.id) AS newer, collect(DISTINCT p.name) AS owners
    """):
        out.append({"id": r["id"], "type": "Decision", "title": r["title"], "owner": ", ".join(r["owners"]),
                    "reviewed_days_ago": None,
                    "reason": f"Referenced by newer {', '.join(r['newer'][:3])}; confirm it still holds",
                    "evidence": r["newer"]})
    out.sort(key=lambda x: -len(x["evidence"]))
    return out


def mark_reviewed(g: Graph, node_id: str, by: str) -> None:
    g.query("""
        MATCH (n) WHERE (n:Runbook OR n:Decision) AND n.id = $id
        SET n.updated_at = $ts, n.reviewed_by = $by
    """, {"id": node_id, "ts": now_ms(), "by": by})
