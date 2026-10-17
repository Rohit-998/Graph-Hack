"""Public demo mode (PUBLIC_DEMO=true): every visitor works in a private copy of the graph.

The template graphs (fb_nimbuspay, fb_meridian) are never written to. On a visitor's first
request their session gets a sandbox, `GRAPH.COPY` of the template (~0.1s), and every API call
in that session is routed to it. Visitors can inject faults, approve actions, add knowledge and
hold conversations without affecting anyone else, which is FalkorDB's one-graph-per-tenant
model running live.

Guards, all in memory (one app instance):
  - sandboxes are capped (least recently used evicted) and expire after an idle TTL
  - per-IP rate limits on writes, chaos injection, LLM-backed calls and new sessions
  - LLM calls also have a global daily cap in the gateway, after which everything runs
    deterministically
"""

import os
import re
import threading
import time
from collections import defaultdict, deque
from contextvars import ContextVar

from .db import client

ENABLED = os.getenv("PUBLIC_DEMO", "false").lower() in ("1", "true", "yes")
MAX_SANDBOXES = int(os.getenv("PUBLIC_MAX_SANDBOXES", "8"))
IDLE_TTL_S = int(os.getenv("PUBLIC_SANDBOX_TTL_S", "1200"))
PREFIX = "fb_s_"
SID_RE = re.compile(r"^[a-z0-9]{12,32}$")
WORLDS = ("nimbuspay", "meridian")

# (key, limit, window seconds)
RULES = {
    "write": (90, 60),          # any POST
    "inject": (12, 60),         # chaos injections
    "llm": (8, 600),            # LLM-backed endpoints
    "session": (10, 3600),      # new sandboxes per IP
}
LLM_PATHS = re.compile(r"^/api/(incidents/[^/]+/llm-investigate|cypher)$")

current_session: ContextVar[str | None] = ContextVar("firebreak_session", default=None)

_lock = threading.Lock()
_sandboxes: dict[str, float] = {}     # graph name -> last used (epoch s)
_world: dict[str, str] = {}           # session id -> world
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


class Limited(Exception):
    def __init__(self, what: str, retry_after: int):
        super().__init__(what)
        self.what = what
        self.retry_after = retry_after


def template(world: str) -> str:
    return f"fb_{world}"


def sandbox_name(sid: str, world: str) -> str:
    return f"{PREFIX}{sid[:12]}_{world}"


def session_world(sid: str) -> str:
    return _world.get(sid, "nimbuspay")


def set_session_world(sid: str, world: str) -> None:
    if world not in WORLDS:
        raise KeyError(world)
    _world[sid] = world


def _allow(ip: str, rule: str) -> None:
    limit, window = RULES[rule]
    q = _hits[(ip, rule)]
    now = time.time()
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise Limited(rule, int(window - (now - q[0])) + 1)
    q.append(now)


def check_rate(ip: str, method: str, path: str) -> None:
    if method != "POST":
        return
    _allow(ip, "write")
    if path == "/api/chaos/inject":
        _allow(ip, "inject")
    if LLM_PATHS.match(path):
        _allow(ip, "llm")


def _drop(name: str) -> None:
    _sandboxes.pop(name, None)
    try:
        client().select_graph(name).delete()
    except Exception:
        pass


def _evict_locked(now: float) -> None:
    for name, last in list(_sandboxes.items()):
        if now - last > IDLE_TTL_S:
            _drop(name)
    while len(_sandboxes) >= MAX_SANDBOXES:
        oldest = min(_sandboxes, key=_sandboxes.get)
        _drop(oldest)


def ensure_sandbox(sid: str, ip: str, world: str | None = None) -> str:
    """The sandbox graph for this session and world, created from the template on first use."""
    world = world or session_world(sid)
    name = sandbox_name(sid, world)
    with _lock:
        now = time.time()
        if name in _sandboxes:
            _sandboxes[name] = now
            return name
        db = client()
        existing = set(db.list_graphs())
        if name not in existing:
            _allow(ip, "session")
            _evict_locked(now)
            db.select_graph(template(world)).copy(name)
        _sandboxes[name] = now
        return name


def live_sandboxes(within_s: float = 120) -> list[str]:
    now = time.time()
    return [n for n, last in _sandboxes.items() if now - last <= within_s]


def sweep() -> None:
    with _lock:
        _evict_locked(time.time())


def template_dirty(name: str) -> bool:
    """A template is dirty if anything beyond the seed was written to it: injected scenario
    changes, open alerts, unresolved incidents, conversations or ingested knowledge."""
    from .db import rows

    g = client().select_graph(name)
    return bool(rows(g, """
        OPTIONAL MATCH (c:Change {scenario: true}) WITH count(c) AS a
        OPTIONAL MATCH (al:Alert {status: 'open'}) WITH a, count(al) AS b
        OPTIONAL MATCH (i:Incident) WHERE i.status <> 'resolved' WITH a, b, count(i) AS c
        OPTIONAL MATCH (u:User) WITH a, b, c, count(u) AS d
        OPTIONAL MATCH (n) WHERE n.ingested = true WITH a, b, c, d, count(n) AS e
        RETURN a + b + c + d + e AS dirt
    """)[0]["dirt"])


def cleanup_on_start() -> int:
    """Delete sandboxes left over from a previous process."""
    db = client()
    stale = [n for n in db.list_graphs() if n.startswith(PREFIX)]
    for n in stale:
        try:
            db.select_graph(n).delete()
        except Exception:
            pass
    return len(stale)


def status() -> dict:
    return {"enabled": ENABLED, "sandboxes": len(_sandboxes), "max_sandboxes": MAX_SANDBOXES,
            "idle_ttl_s": IDLE_TTL_S}
