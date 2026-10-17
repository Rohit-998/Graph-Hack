"""HTTP API for Mission Control (PRD §12.2).

Run: uv run uvicorn firebreak.api:app --reload --port 8000
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agents, embeddings, graph_algos, incidents, investigator, knowledge, memory, preflight
from . import public
from . import simulator as sim
from .llm import gateway
from . import tools as T
from .config import settings
from .db import active_graph_name, client, graph, reset_request_graph, rows, set_active_graph, use_graph_for_request

TICK_SECONDS = 2.0


async def _tick_one(name: str) -> None:
    g = graph(name)
    await asyncio.to_thread(sim.tick, g)
    iid = await asyncio.to_thread(incidents.open_incident, g)
    if iid:
        await agents.investigate(g, iid)


async def _ticker() -> None:
    """Background simulator loop: recompute health and open incidents from new alerts.
    In public mode it ticks every sandbox a visitor used recently, never the templates."""
    n = 0
    while True:
        try:
            names = public.live_sandboxes() if public.ENABLED else [active_graph_name()]
            for name in names:
                try:
                    await _tick_one(name)
                except Exception as exc:
                    print(f"[ticker] {name}: {exc!r}")
            n += 1
            if public.ENABLED and n % 30 == 0:
                await asyncio.to_thread(public.sweep)
        except Exception as exc:  # keep the loop alive; surface in logs
            print(f"[ticker] {exc!r}")
        await asyncio.sleep(TICK_SECONDS)


def _ensure_seeded() -> None:
    """First start (e.g. fresh docker compose up): build the tenant graph if it isn't there.
    Public mode needs both company templates, and clears sandboxes from a previous run."""
    from .seed import seed

    for attempt in range(30):
        try:
            have = set(client().list_graphs())
            if public.ENABLED:
                # Reseed a template only if it is missing or was written to, so a cold start
                # (free hosts sleep when idle) doesn't pay for a full seed every time.
                for world in public.WORLDS:
                    name = public.template(world)
                    if name not in have or public.template_dirty(name):
                        print(f"[startup] seeding template {name}")
                        seed(world, world)
                    else:
                        print(f"[startup] template {name} is clean")
                print(f"[startup] removed {public.cleanup_on_start()} stale sandboxes")
            elif settings.graph_name not in have:
                print(f"[startup] seeding {settings.graph_name}")
                seed()
            return
        except Exception as exc:  # FalkorDB still starting
            print(f"[startup] waiting for FalkorDB ({attempt + 1}/30): {exc!r}")
            time.sleep(2)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(_ensure_seeded)
    task = asyncio.create_task(_ticker())
    yield
    task.cancel()


app = FastAPI(title="Firebreak", version="0.1.0", lifespan=lifespan)

SESSION_COOKIE = "fb_session"


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


@app.middleware("http")
async def public_sandbox(request: Request, call_next):
    """Public demo: give each visitor a private copy of the graph and rate-limit writes."""
    if not public.ENABLED or not request.url.path.startswith("/api/"):
        return await call_next(request)
    ip = _client_ip(request)
    sid = request.cookies.get(SESSION_COOKIE)
    new = not (sid and public.SID_RE.match(sid))
    if new:
        sid = secrets.token_hex(8)
    try:
        public.check_rate(ip, request.method, request.url.path)
        name = await asyncio.to_thread(public.ensure_sandbox, sid, ip)
    except public.Limited as lim:
        return JSONResponse({"detail": f"rate limited ({lim.what}); try again in {lim.retry_after}s"},
                            status_code=429, headers={"Retry-After": str(lim.retry_after)})
    token = use_graph_for_request(name)
    sess = public.current_session.set(sid)
    try:
        response = await call_next(request)
    finally:
        reset_request_graph(token)
        public.current_session.reset(sess)
    if new:
        response.set_cookie(SESSION_COOKIE, sid, max_age=public.IDLE_TTL_S, httponly=True, samesite="lax")
    return response
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
    user: str = "guest"
    conversation: str | None = None


class ApproveRequest(BaseModel):
    by: str = "human"


@app.get("/api/health")
def health():
    try:
        ok = active_graph_name() in client().list_graphs()
    except Exception as exc:
        return {"ok": False, "falkordb": repr(exc)}
    return {"ok": ok, "graph": active_graph_name(), "llm": gateway.status(), "embeddings": embeddings.backend(),
            "public": public.status()}


WORLD_LABEL = {"nimbuspay": "NimbusPay · fintech", "meridian": "Meridian · streaming"}


@app.get("/api/worlds")
def list_worlds():
    """Every synthetic company, each in its own FalkorDB graph."""
    from . import worlds as W

    have = set(client().list_graphs())
    return {"active": active_graph_name(), "worlds": [
        {"name": n, "label": WORLD_LABEL.get(n, n), "graph": f"fb_{n}", "seeded": f"fb_{n}" in have,
         "components": len(m.COMPONENTS), "people": len(m.PEOPLE), "incidents": len(m.INCIDENTS)}
        for n, m in W.WORLDS.items()]}


@app.post("/api/worlds/{name}/activate")
async def activate_world(name: str, request: Request):
    """Switch the live graph. Seeds the world on first use; memory in each graph is kept."""
    from . import worlds as W
    from .seed import seed

    if name not in W.WORLDS:
        raise HTTPException(404, f"unknown world {name}")
    if public.ENABLED:
        # Public: switch only this visitor's session, into their own copy of that company.
        sid = public.current_session.get()
        public.set_session_world(sid, name)
        gname = await asyncio.to_thread(public.ensure_sandbox, sid, _client_ip(request), name)
        graph_algos.invalidate()
        return {"active": gname, "world": name}
    gname = f"fb_{name}"
    if gname not in client().list_graphs():
        await asyncio.to_thread(seed, name, name)
    set_active_graph(gname)
    graph_algos.invalidate()
    return {"active": gname, "world": name}


@app.get("/api/llm")
def llm_status():
    return gateway.status()


@app.get("/api/memory/playbooks")
def playbooks():
    return rows(graph(), """
        MATCH (p:Playbook)-[:FOR]->(c:Component)
        RETURN p.id AS id, p.kind AS kind, c.name AS component, p.success_count AS success,
               p.failure_count AS failure
        ORDER BY success DESC, component
    """)


@app.get("/api/memory/learning-curve")
def learning_curve():
    return memory.learning_curve(graph())


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
    world = rows(g, "MATCH (w:World) RETURN w.name AS n LIMIT 1")
    wname = world[0]["n"] if world else None
    return {"nodes": nodes, "edges": edges, "stats": {"components": len(nodes), **stats},
            "world": {"name": wname, "label": WORLD_LABEL.get(wname, wname), "graph": active_graph_name()}}


@app.get("/api/scenarios")
def list_scenarios():
    return [{"id": s.id, "title": s.title, "root": s.root, "remediation": s.remediation}
            for s in sim.scenarios(graph())]


@app.post("/api/chaos/inject")
async def inject(req: InjectRequest):
    if req.scenario not in sim.scenario_map(graph()):
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
    incidents.close_open(g)
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


@app.post("/api/incidents/{iid}/llm-investigate")
async def llm_investigate(iid: str):
    """Second opinion: an LLM picks graph tools itself, then its verdict is checked against the graph's."""
    g = graph()
    if not gateway.enabled:
        raise HTTPException(409, "LLM disabled; set LLM_PROVIDER and LLM_API_KEYS")
    return await asyncio.to_thread(investigator.run, g, iid)


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
    """Company-brain Q&A. Conversations persist in the graph per user; follow-ups resolve
    against the entities the previous answer cited."""
    from . import conversation as conv
    try:
        return conv.ask(graph(), req.user, req.question, req.conversation)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.get("/api/conversations")
def list_conversations(user: str = "guest"):
    from . import conversation as conv
    return conv.conversations(graph(), user)


@app.get("/api/conversations/{cid}")
def get_conversation(cid: str, user: str = "guest"):
    from . import conversation as conv
    try:
        return conv.history(graph(), user, cid)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.get("/api/algorithms")
def algorithms():
    """FalkorDB PageRank and betweenness over the live dependency graph."""
    g = graph()
    pr, bw = graph_algos.pagerank(g), graph_algos.betweenness(g)
    return {
        "page_rank": {"algorithm": pr.algorithm, "duration_ms": round(pr.duration_ms, 2), "top": pr.top(8)},
        "betweenness": {"algorithm": bw.algorithm, "duration_ms": round(bw.duration_ms, 2), "top": bw.top(8)},
    }


@app.get("/api/spof")
def spof():
    """Single points of failure: choke points by betweenness, with owners and on-call."""
    return graph_algos.spof_scan(graph(), top=6)


class PreflightRequest(BaseModel):
    component: str
    kind: str = "deploy"
    author: str | None = None


@app.post("/api/preflight")
def preflight_check(req: PreflightRequest):
    """Pre-deploy risk: what the graph knows about shipping this change, before it ships."""
    try:
        return preflight.check(graph(), req.component, req.kind, req.author)
    except KeyError:
        raise HTTPException(404, f"unknown component {req.component}")


class IngestRequest(BaseModel):
    kind: str            # doc | ticket | chat
    title: str
    body: str
    author: str | None = None
    status: str | None = None
    channel: str | None = None


@app.post("/api/knowledge")
def ingest_knowledge(req: IngestRequest):
    """Add a doc, ticket or chat message; it is linked to the components, people and records it
    names, and is searchable by Ask immediately. The extracted links are returned."""
    try:
        return knowledge.ingest(graph(), req.kind, req.title, req.body, req.author, req.status, req.channel)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/api/knowledge/stale")
def stale_knowledge():
    """Runbooks and decisions their subject has outgrown, each with the reason."""
    return knowledge.stale(graph())


class ReviewRequest(BaseModel):
    by: str = "human"


@app.post("/api/knowledge/{node_id}/reviewed")
def mark_reviewed(node_id: str, req: ReviewRequest | None = None):
    knowledge.mark_reviewed(graph(), node_id, (req or ReviewRequest()).by)
    return {"id": node_id, "reviewed": True}


class CypherRequest(BaseModel):
    question: str | None = None   # natural language -> LLM writes the query
    cypher: str | None = None     # or run your own


@app.post("/api/cypher")
def cypher(req: CypherRequest):
    """Guarded read-only Cypher over the active graph. Writes are rejected by FalkorDB itself
    (GRAPH.RO_QUERY), with a timeout and a row cap. The query that ran is always returned."""
    from . import cypher_tool as C

    g = graph()
    try:
        if req.cypher:
            return C.run_readonly(g, req.cypher)
        if req.question:
            return C.ask(g, req.question)
    except C.CypherRejected as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    raise HTTPException(422, "send either question or cypher")


@app.get("/api/schema")
def graph_schema():
    from . import cypher_tool as C
    return C.schema(graph())


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


# Serve the built Mission Control UI from the same origin (Docker image / `npm run build`).
# Registered last so /api routes take precedence.
UI_DIST = Path(os.getenv("FIREBREAK_UI_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if UI_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
