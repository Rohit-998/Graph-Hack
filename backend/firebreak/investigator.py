"""LLM investigator: tool selection over the graph (opt-in, Track 01 "tool selection through MCP").

The deterministic Commander is the default and always the verifier. This module adds a second
way to reach a verdict: an LLM is handed the *same* read-only graph tools the MCP server exposes
and chooses which to call, step by step. It never sees the answer directly; its only truth is
tool output.

Guardrails:
  - The LLM's verdict is accepted only if it cites a change/component id returned by a tool.
  - It is compared against the graph RCA; disagreement is recorded, never silently used.
  - Every call is limited, timed and written to the graph as an AgentStep, so judges can audit.
"""

import json
import time

from falkordb import Graph

from . import agents, memory
from . import simulator as sim
from . import tools as T
from .db import rows
from .llm import gateway

MAX_STEPS = 3

TOOL_SPEC = [
    {"name": "rank_root_causes",
     "args": {"alerting": "list of component names that alerted (optional)"},
     "returns": "candidates with confidence, coverage, the change on each, and rejected decoys"},
    {"name": "blast_radius", "args": {"component": "component name"},
     "returns": "components that depend on it, with impact down/degraded, plus customers and $/hr"},
    {"name": "who_knows", "args": {"component": "component name"},
     "returns": "owning team, on-call and ranked experts with reasons"},
    {"name": "similar_incidents", "args": {"description": "text", "components": "list of component names"},
     "returns": "past incidents with root cause, the fix that worked and time to mitigate"},
    {"name": "evidence_path", "args": {"from_component": "alerting service", "to_component": "suspect"},
     "returns": "dependency path between them"},
]

SYSTEM = (
    "You are an incident investigator with access to read-only graph tools. Decide what to call next. "
    "Reply with JSON only, either {\"tool\": <name>, \"args\": {...}, \"why\": <one sentence>} "
    "or {\"final\": {\"root_cause\": <change id or component name>, \"confidence\": <0-1>, \"reasoning\": <2 sentences>}}. "
    "Prefer the change id; the component carrying it is also accepted. Only name a root cause that appeared in a tool result."
)


def _call(g: Graph, iid: str, name: str, args: dict) -> dict:
    t0 = time.perf_counter()
    if name == "rank_root_causes":
        alerting = args.get("alerting") or agents_alerting(g, iid)
        ranked, rejected, calls = T.rank_root_causes(g, alerting, sim.now_ms())
        out = {
            "alerting": alerting,
            "candidates": [{"component": r.component, "confidence": round(r.confidence, 3),
                            "change": r.top_change and {"id": r.top_change.id, "kind": r.top_change.kind,
                                                        "author": r.top_change.author},
                            "breakdown": r.breakdown}
                           for r in ranked[:5] if r.has_evidence],
            "rejected_decoys": [{"change": c["change"], "component": c["component"]} for c in rejected],
        }
        cypher = calls[0].cypher
    elif name == "blast_radius":
        br, bi = T.blast_radius(g, args["component"]), T.business_impact(g, args["component"])
        out = {"upstream": br.data[:8], "customers": bi.data, "cypher": br.cypher}
        cypher = br.cypher
    elif name == "who_knows":
        oc = T.owners_and_oncall(g, args["component"], sim.now_ms())
        out = {"on_call": oc.data, "experts": T.who_knows(g, args["component"]).data}
        cypher = oc.cypher
    elif name == "similar_incidents":
        out = {"matches": memory.similar_incidents(g, "", args.get("components") or [],
                                                   args.get("description", ""))[0]}
        cypher = "CALL db.idx.vector.queryNodes('Incident', 'embedding', ...)"
    elif name == "evidence_path":
        res = T.evidence_path(g, args["from_component"], args["to_component"])
        out = {"path": res.data[0]["path"] if res.data else None}
        cypher = res.cypher
    else:
        out = {"error": f"unknown tool {name}"}
        cypher = ""
    agents.record_step(g, iid, "investigator", name, cypher,
                       f"LLM called {name}({', '.join(f'{k}={v}' for k, v in args.items())[:80]})",
                       (time.perf_counter() - t0) * 1000, model=gateway.model)
    return out


def agents_alerting(g: Graph, iid: str) -> list[str]:
    from .incidents import alerting_components

    return alerting_components(g, iid)


def run(g: Graph, iid: str) -> dict:
    """Ask the LLM to investigate, then check it against the graph RCA."""
    if not gateway.enabled:
        return {"incident": iid, "error": "LLM disabled (LLM_PROVIDER=none)"}

    alerting = agents_alerting(g, iid)
    transcript: list[dict] = []
    history = [{"role": "user",
                "content": json.dumps({"alerts": [{"service": a} for a in alerting], "tools": TOOL_SPEC})}]

    for _ in range(MAX_STEPS):
        reply = gateway.chat_json(SYSTEM, "\n\n".join(m["content"] for m in history), max_tokens=400)
        if not reply:
            break
        if "final" in reply:
            transcript.append(reply)
            break
        name, args = reply.get("tool"), reply.get("args") or {}
        result = _call(g, iid, name, args)
        transcript.append({"tool": name, "args": args, "result": result, "why": reply.get("why")})
        history.append({"role": "assistant", "content": json.dumps(reply)})
        history.append({"role": "user", "content": "TOOL RESULT: " + json.dumps(result)[:2500]})

    final = next((t["final"] for t in transcript if "final" in t), None)
    # The graph RCA is the reference answer.
    deterministic = rows(g, """
        MATCH (:Incident {id: $iid})-[:HAS_HYPOTHESIS]->(h:Hypothesis {status: 'accepted'})-[:SUSPECTS]->(s)
        OPTIONAL MATCH (s)-[:CHANGED]->(c:Component)
        RETURN coalesce(s.id, s.name) AS id, coalesce(c.name, s.name) AS component
    """, {"iid": iid})
    graph_answer = deterministic[0]["id"] if deterministic else None

    seen = json.dumps(transcript)
    cited = bool(final and str(final.get("root_cause", "")) and str(final["root_cause"]) in seen)
    # Naming the component that carries the root-cause change counts as the same answer.
    graph_component = deterministic[0]["component"] if deterministic else None
    answer = str((final or {}).get("root_cause", "")).strip()
    agrees = bool(answer and answer in (graph_answer, graph_component))

    if final:
        rows_id = f"HYP-{iid}-llm"
        g.query("""
            MATCH (i:Incident {id: $iid})
            MERGE (h:Hypothesis {id: $id})
            SET h.statement = $stmt, h.confidence = $conf, h.proposed_by = 'investigator',
                h.status = $status, h.breakdown = $bd
            MERGE (i)-[:HAS_HYPOTHESIS]->(h)
        """, {"iid": iid, "id": rows_id,
              "stmt": f"LLM investigator: {final['root_cause']} — {final.get('reasoning', '')[:160]}",
              "conf": float(final.get("confidence") or 0), "bd": json.dumps({"agrees_with_graph": agrees}),
              "status": "proposed" if agrees else "rejected"})
        agents.record_step(g, iid, "investigator", "verdict", "",
                           f"LLM verdict {final['root_cause']} ({float(final.get('confidence') or 0):.0%}) — "
                           f"{'agrees with' if agrees else 'disagrees with'} graph RCA "
                           f"{graph_answer} ({graph_component})",
                           0, model=gateway.model)
    return {"incident": iid, "transcript": transcript, "llm_verdict": final,
            "graph_verdict": graph_answer, "agrees": agrees, "cited_tool_output": cited,
            "accepted": agrees and cited}
