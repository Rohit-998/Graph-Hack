"""Guarded read-only Cypher (PRD FR-P1.8): text-to-Cypher over the live schema.

Safety is enforced by the database, not by string matching:
  - every query runs through GRAPH.RO_QUERY, which FalkorDB rejects if it would write
  - a server-side timeout and a row cap bound the cost
  - the query only ever sees the active tenant's graph
A keyword pre-check exists only to return a clearer error before the round trip.

The LLM is given the actual schema (labels, relationship types and properties sampled from the
graph), writes one query, and gets one repair attempt if FalkorDB rejects it. The Cypher it wrote
is always returned, so the answer is auditable.
"""

import re
import time

from falkordb import Graph

from .db import rows
from .llm import gateway

ROW_LIMIT = 200
TIMEOUT_MS = 2000
WRITE_WORDS = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|LOAD\s+CSV)\b", re.I)
INDEX_CALLS = re.compile(r"\bCALL\s+db\.idx\.\w+\.(create|drop)", re.I)
STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


class CypherRejected(ValueError):
    pass


def _jsonable(v):
    """Nodes, edges and paths from the client become plain dicts."""
    if hasattr(v, "properties") and hasattr(v, "labels"):
        return {"labels": list(v.labels), **v.properties}
    if hasattr(v, "properties") and hasattr(v, "relation"):
        return {"type": v.relation, **v.properties}
    if hasattr(v, "nodes") and callable(getattr(v, "nodes")):
        return {"path": [_jsonable(n) for n in v.nodes()]}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


def run_readonly(g: Graph, cypher: str, params: dict | None = None,
                 limit: int = ROW_LIMIT, timeout_ms: int = TIMEOUT_MS) -> dict:
    cypher = cypher.strip().rstrip(";")
    if not cypher:
        raise CypherRejected("empty query")
    # Ignore string literals so a value like 'Create invoice' isn't mistaken for a write.
    # FalkorDB's RO_QUERY is the real guard; this only gives a clearer error.
    code = STRING_LITERAL.sub("''", cypher)
    if WRITE_WORDS.search(code) or INDEX_CALLS.search(code):
        raise CypherRejected("read-only: queries that write or change indexes are not allowed")
    t0 = time.perf_counter()
    try:
        res = g.ro_query(cypher, params or {}, timeout=timeout_ms)
    except Exception as exc:
        raise CypherRejected(str(exc)) from exc
    cols = [h[1] if isinstance(h, (list, tuple)) else h for h in res.header]
    data = [dict(zip(cols, (_jsonable(v) for v in r))) for r in res.result_set[:limit]]
    return {"cypher": cypher, "columns": cols, "rows": data, "row_count": len(res.result_set),
            "truncated": len(res.result_set) > limit, "duration_ms": round((time.perf_counter() - t0) * 1000, 1)}


def schema(g: Graph) -> dict:
    """Labels with sampled property keys, and relationship types with their endpoints."""
    labels = [r["label"] for r in rows(g, "CALL db.labels() YIELD label RETURN label")]
    out_labels = {}
    for lab in labels:
        props = rows(g, f"MATCH (n:{lab}) WITH n LIMIT 25 UNWIND keys(n) AS k RETURN DISTINCT k AS k")
        out_labels[lab] = sorted(p["k"] for p in props if p["k"] != "embedding")
    rels = rows(g, """
        MATCH (a)-[r]->(b)
        WITH type(r) AS t, labels(a)[0] AS src, labels(b)[0] AS dst, count(*) AS n
        RETURN t, src, dst, n ORDER BY t, n DESC
    """)
    out_rels: dict[str, list[str]] = {}
    for r in rels:
        out_rels.setdefault(r["t"], []).append(f"(:{r['src']})-[:{r['t']}]->(:{r['dst']})")
    # Edge properties matter (USES.gmv_per_hour_usd, DEPENDS_ON.mode, ON_CALL.level ...).
    rel_props = {}
    for t in out_rels:
        keys = rows(g, f"MATCH ()-[r:{t}]->() WITH r LIMIT 25 UNWIND keys(r) AS k RETURN DISTINCT k AS k")
        rel_props[t] = sorted(k["k"] for k in keys)
    return {"labels": out_labels, "relationships": {k: v[:3] for k, v in out_rels.items()},
            "relationship_properties": rel_props}


def _schema_text(s: dict) -> str:
    lines = ["Node labels and properties:"]
    lines += [f"  {lab}: {', '.join(props)}" for lab, props in s["labels"].items()]
    lines.append("Relationships (with their properties):")
    for t, pats in s["relationships"].items():
        props = s.get("relationship_properties", {}).get(t) or []
        lines.append(f"  {', '.join(pats)}" + (f"  {{{', '.join(props)}}}" if props else ""))
    return "\n".join(lines)


SYSTEM = (
    "You translate questions about a company's operational knowledge graph into ONE read-only Cypher "
    "query for FalkorDB. Use only labels, relationship types and properties from the schema. Never write "
    "(no CREATE, MERGE, SET, DELETE, REMOVE). Always end with LIMIT 50 or less. Return named columns, "
    "not whole nodes. Reply with JSON only: {\"cypher\": \"...\", \"explanation\": \"one sentence\"}."
)

EXAMPLE = (
    "Example. Question: who owns the services that checkout-api depends on?\n"
    "{\"cypher\": \"MATCH (:Component {name: 'checkout-api'})-[:DEPENDS_ON]->(c:Component)<-[:OWNS]-(t:Team) "
    "RETURN c.name AS component, t.name AS team ORDER BY component LIMIT 50\", "
    "\"explanation\": \"Direct dependencies of checkout-api with their owning team.\"}"
)


def ask(g: Graph, question: str) -> dict:
    """Text-to-Cypher with one repair attempt. Raises if the LLM is not configured."""
    if not gateway.enabled:
        raise RuntimeError("LLM disabled; set LLM_PROVIDER and LLM_API_KEYS, or run Cypher directly")
    sch = schema(g)
    prompt = f"{_schema_text(sch)}\n\n{EXAMPLE}\n\nQuestion: {question}"
    attempts = []
    for _ in range(2):
        reply = gateway.chat_json(SYSTEM, prompt, max_tokens=400, use_cache=False)
        if not reply or not reply.get("cypher"):
            attempts.append({"error": gateway.usage.last_error or "no query produced"})
            break
        cypher = reply["cypher"]
        try:
            result = run_readonly(g, cypher)
            return {"question": question, "explanation": reply.get("explanation", ""), **result,
                    "attempts": attempts + [{"cypher": cypher, "ok": True}], "model": gateway.model}
        except CypherRejected as exc:
            attempts.append({"cypher": cypher, "error": str(exc)[:200]})
            prompt += (f"\n\nYour query:\n{cypher}\nwas rejected by FalkorDB: {str(exc)[:200]}\n"
                       "Fix it and reply with the same JSON shape.")
    return {"question": question, "error": "could not produce a valid read-only query",
            "attempts": attempts, "model": gateway.model}
