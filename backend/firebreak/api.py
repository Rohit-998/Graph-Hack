"""HTTP API for Mission Control (PRD §12.2).

Run: uv run uvicorn firebreak.api:app --reload --port 8000
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agents, incidents
from . import simulator as sim
from . import tools as T
from .config import settings
from .db import client, graph, rows

TICK_SECONDS = 2.0


async def _ticker() -> None:
    """Background simulator loop: recompute health and open incidents from new alerts."""
    while True:
        try:
            g = graph()
            await asyncio.to_thread(sim.tick, g)
            iid = await asyncio.to_thread(incidents.open_incident, g)
            if iid:
                await agents.investigate(g, iid)
        except Exception as exc:  # keep the loop alive; surface in logs
            print(f"[ticker] {exc!r}")
        await asyncio.sleep(TICK_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_ticker())
    yield
    task.cancel()


app = FastAPI(title="Firebreak", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InjectRequest(BaseModel):
    scenario: str
    with_decoy: bool = True


class AskRequest(BaseModel):
    question: str


class ApproveRequest(BaseModel):
    by: str = "human"


@app.get("/api/health")
def health():
    try:
        ok = settings.graph_name in client().list_graphs()
    except Exception as exc:
        return {"ok": False, "falkordb": repr(exc)}
    return {"ok": ok, "graph": settings.graph_name, "llm": settings.llm_provider, "mode": agents.MODEL}


@app.get("/api/topology")
def topology():
    g = graph()
    nodes = rows(g, """
        MATCH (c:Component)<-[:OWNS]-(t:Team)
        RETURN c.name AS id, c.kind AS kind, c.tier AS tier, c.status AS status, c.lagging AS lagging,
               c.error_rate AS error_rate, c.p95_ms AS p95_ms, c.customer_facing AS customer_facing,
               c.description AS description, t.name AS team
    """)
    edges = rows(g, """
        MATCH (a:Component)-[r:DEPENDS_ON]->(b:Component)
        RETURN a.name AS source, b.name AS target, r.mode AS mode, r.protocol AS protocol
    """)
    stats = rows(g, """
        MATCH (p:Person) WITH count(p) AS people
        MATCH (c:Customer) WITH people, count(c) AS customers
        MATCH (i:Incident) RETURN people, customers, count(i) AS incidents
    """)[0]
    return {"nodes": nodes, "edges": edges, "stats": {"components": len(nodes), **stats}}


@app.get("/api/scenarios")
def scenarios():
    return [{"id": s.id, "title": s.title, "root": s.root, "remediation": s.remediation,
             "decoy": s.decoy["component"]} for s in sim.SCENARIOS.values()]


@app.post("/api/chaos/inject")
async def inject(req: InjectRequest):
    if req.scenario not in sim.SCENARIOS:
        raise HTTPException(404, f"unknown scenario {req.scenario}")
    g = graph()
    out = await asyncio.to_thread(sim.inject, g, req.scenario, req.with_decoy)
    iid = await asyncio.to_thread(incidents.open_incident, g)
    if iid:
        out["incident"] = iid
        out["verdict"] = await agents.investigate(g, iid)
    return out


@app.post("/api/chaos/reset")
def reset():
    g = graph()
    unhealthy = sim.reset(g)
    g.query("""
        MATCH (i:Incident) WHERE i.status IN ['investigating', 'identified', 'mitigating']
        SET i.status = 'resolved', i.resolved_at = $ts, i.closed_by = 'reset'
    """, {"ts": sim.now_ms()})
    return {"unhealthy": unhealthy}


@app.get("/api/incidents")
def list_incidents():
    return incidents.list_incidents(graph())


@app.get("/api/incidents/{iid}")
def get_incident(iid: str):
    d = incidents.detail(graph(), iid)
    if d is None:
        raise HTTPException(404, f"unknown incident {iid}")
    return d


@app.post("/api/incidents/{iid}/investigate")
async def investigate(iid: str):
    g = graph()
    if incidents.detail(g, iid) is None:
        raise HTTPException(404, f"unknown incident {iid}")
    return await agents.investigate(g, iid)


@app.post("/api/actions/{aid}/approve")
def approve(aid: str, req: ApproveRequest | None = None):
    try:
        return incidents.approve_action(graph(), aid, (req or ApproveRequest()).by, background=True)
    except KeyError:
        raise HTTPException(404, f"unknown action {aid}")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/actions/{aid}/reject")
def reject(aid: str, req: ApproveRequest | None = None):
    incidents.reject_action(graph(), aid, (req or ApproveRequest()).by)
    return {"action": aid, "status": "rejected"}


@app.post("/api/ask")
def ask(req: AskRequest):
    from .brain import answer
    return answer(graph(), req.question)


@app.get("/api/components/{name}")
def component(name: str):
    g = graph()
    info = rows(g, "MATCH (c:Component {name: $n})<-[:OWNS]-(t:Team) RETURN properties(c) AS c, t.name AS team",
                {"n": name})
    if not info:
        raise HTTPException(404, f"unknown component {name}")
    return {
        **info[0]["c"], "team": info[0]["team"],
        "blast_radius": T.blast_radius(g, name).data,
        "customers": T.business_impact(g, name).data,
        "experts": T.who_knows(g, name).data,
        "on_call": T.owners_and_oncall(g, name, sim.now_ms()).data,
    }
