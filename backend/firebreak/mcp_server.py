"""Firebreak graph tools over MCP (PRD FR-P1.1).

The same Cypher-backed tools the internal agents use, exposed to any MCP client
(Claude Desktop, Cursor, ...). Every tool is read-only; actions still require
human approval in Mission Control.

  stdio:  uv run python -m firebreak.mcp_server
  HTTP:   uv run python -m firebreak.mcp_server --http   (streamable HTTP on :8001/mcp)
"""

import argparse

from mcp.server.fastmcp import FastMCP

from . import graph_algos, knowledge, memory, preflight
from . import simulator as sim
from . import tools as T
from .brain import answer
from .db import graph, rows

mcp = FastMCP("firebreak", host="127.0.0.1", port=8001)


def _open_alerting() -> list[str]:
    return [r["c"] for r in rows(graph(), "MATCH (a:Alert {status: 'open'})-[:FIRED_ON]->(c) RETURN DISTINCT c.name AS c")]


@mcp.tool()
def rank_root_causes(alerting: list[str] | None = None, top: int = 5) -> dict:
    """Rank likely root causes for the given alerting services (defaults to services with open alerts).

    Traces DEPENDS_ON paths from each alerting service, finds recent changes on every component in the
    closure, and scores candidates by alert coverage, change recency and risk, anomaly, history and
    criticality. Changes no alerting service depends on are returned as rejected decoys."""
    g = graph()
    alerting = alerting or _open_alerting()
    if not alerting:
        return {"alerting": [], "candidates": [], "note": "no open alerts"}
    ranked, rejected, calls = T.rank_root_causes(g, alerting, sim.now_ms())
    return {
        "alerting": alerting,
        "candidates": [
            {"component": r.component, "confidence": round(r.confidence, 3), "coverage": round(r.coverage, 3),
             "change": r.top_change and {"id": r.top_change.id, "kind": r.top_change.kind,
                                         "summary": r.top_change.summary, "author": r.top_change.author},
             "breakdown": r.breakdown}
            for r in ranked[:top] if r.has_evidence
        ],
        "rejected_decoys": [{"change": c["change"], "component": c["component"], "coverage": 0} for c in rejected],
        "cypher": [c.cypher for c in calls[:2]],
    }


@mcp.tool()
def blast_radius(component: str) -> dict:
    """Everything that transitively depends on `component`, with hop count and impact (down if every
    edge on the path is synchronous, else degraded), plus customers and GMV/hour exposed."""
    g = graph()
    br, bi = T.blast_radius(g, component), T.business_impact(g, component)
    return {"component": component, "upstream": br.data, "customers": bi.data,
            "gmv_per_hour": sum(c["gmv_per_hour"] or 0 for c in bi.data), "cypher": [br.cypher, bi.cypher]}


@mcp.tool()
def evidence_path(from_component: str, to_component: str) -> dict:
    """Shortest DEPENDS_ON path from an alerting service to a suspected cause."""
    res = T.evidence_path(graph(), from_component, to_component)
    return {"path": res.data[0]["path"] if res.data else None, "cypher": res.cypher}


@mcp.tool()
def who_knows(component: str) -> dict:
    """Owner team, current on-call with escalation, and the top experts for a component (from past
    incident response, runbooks, changes and learned expertise)."""
    g = graph()
    return {"component": component, "on_call": T.owners_and_oncall(g, component, sim.now_ms()).data,
            "experts": T.who_knows(g, component).data}


@mcp.tool()
def similar_incidents(description: str, components: list[str] | None = None) -> dict:
    """Find past incidents similar to a description (vector search) weighted by overlap with the given
    components. Returns each match's root cause, the fix that worked and time to mitigate."""
    similar, cypher = memory.similar_incidents(graph(), "", components or [], description, top=5)
    keep = ("id", "title", "score", "similarity", "overlap_ratio", "rc_component", "rc_change", "actions", "ttm_min")
    return {"matches": [{k: s[k] for k in keep} for s in similar], "cypher": cypher}


@mcp.tool()
def criticality_rank(top: int = 5) -> dict:
    """Components the rest of the system depends on most, by FalkorDB PageRank over DEPENDS_ON,
    plus the top choke points by betweenness centrality."""
    g = graph()
    pr, bw = graph_algos.pagerank(g), graph_algos.betweenness(g)
    return {"page_rank": pr.top(top), "betweenness": bw.top(top),
            "cypher": [pr.cypher, bw.cypher.strip()]}


@mcp.tool()
def single_points_of_failure(top: int = 5) -> dict:
    """Components whose failure would break the most unrelated dependency paths, with owning team,
    dependents and current on-call."""
    return {"choke_points": graph_algos.spof_scan(graph(), top)}


@mcp.tool()
def preflight_change(component: str, kind: str = "deploy") -> dict:
    """Risk of shipping a change (deploy, config, flag or migration) to `component`, before it ships:
    blast radius, customers exposed, choke-point centrality, what broke the last times this kind of
    change hit it, changes already in flight nearby, relevant decisions, and who should review."""
    r = preflight.check(graph(), component, kind)
    keep = ("component", "kind", "risk", "score", "factors", "gmv_per_hour", "betweenness",
            "past_incidents", "in_flight", "decisions", "reviewers", "advice")
    return {k: r[k] for k in keep}


@mcp.tool()
def stale_knowledge() -> dict:
    """Runbooks and decisions that their subject has outgrown (incidents since last review, or newer
    documents referencing them), each with the reason and the evidence ids."""
    return {"stale": knowledge.stale(graph())}


@mcp.tool()
def graph_schema() -> dict:
    """Node labels with their properties and relationship types with endpoints and properties,
    sampled from the live graph. Read this before writing Cypher."""
    from . import cypher_tool as C
    return C.schema(graph())


@mcp.tool()
def readonly_cypher(cypher: str) -> dict:
    """Run a read-only Cypher query against the graph. Enforced by FalkorDB (GRAPH.RO_QUERY): any
    write is rejected. 2s timeout, 200-row cap."""
    from . import cypher_tool as C
    try:
        return C.run_readonly(graph(), cypher)
    except C.CypherRejected as exc:
        return {"error": str(exc), "cypher": cypher}


@mcp.tool()
def ask_company_brain(question: str) -> dict:
    """Answer a question about how the company works (decisions, runbooks, discussions, past incidents)
    with cited sources from the knowledge graph."""
    a = answer(graph(), question)
    return {k: a[k] for k in ("answer", "sources", "highlight")}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--http", action="store_true", help="serve streamable HTTP on 127.0.0.1:8001/mcp")
    a = p.parse_args()
    mcp.run(transport="streamable-http" if a.http else "stdio")


if __name__ == "__main__":
    main()
