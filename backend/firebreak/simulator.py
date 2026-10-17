"""Telemetry simulator and chaos lab (PRD FR-2.x).

FalkorDB is the source of truth: the simulator reads DEPENDS_ON topology and
active faults (properties on Component) from the graph, computes health, and
writes status, metrics and Alert nodes back.

Propagation rules (v1):
  - sync edge:  errors and latency flow from a dependency to its caller, attenuated per hop
  - async edge: only lag flows; the caller's status is unaffected
Alert rules fire on customer-facing components only (symptoms, not causes).
"""

import random
import time
import zlib
from dataclasses import dataclass, replace

from falkordb import Graph

from . import worlds
from .db import rows

HOP_ATTENUATION = 0.85
DEGRADED_ERROR = 0.05
DOWN_ERROR = 0.30
ALERT_ERROR = 0.05
ALERT_LATENCY_MULT = 2.0
MIN = 60_000


@dataclass(frozen=True)
class Fault:
    error_rate: float
    latency_mult: float


@dataclass
class Health:
    error_rate: float
    latency_mult: float
    lagging: bool = False

    @property
    def status(self) -> str:
        if self.error_rate >= DOWN_ERROR:
            return "down"
        if self.error_rate >= DEGRADED_ERROR or self.latency_mult >= ALERT_LATENCY_MULT:
            return "degraded"
        return "healthy"


def propagate(
    components: list[str], edges: list[tuple[str, str, str]], faults: dict[str, Fault]
) -> dict[str, Health]:
    """edges are (caller, dependency, mode). Returns health for every component."""
    deps: dict[str, list[tuple[str, str]]] = {c: [] for c in components}
    for a, b, mode in edges:
        deps[a].append((b, mode))

    memo: dict[str, Health] = {}

    def health(c: str) -> Health:
        if c in memo:
            return memo[c]
        own = faults.get(c)
        err = own.error_rate if own else 0.0
        lat = own.latency_mult if own else 1.0
        lag = False
        for d, mode in deps[c]:
            h = health(d)
            if mode == "sync":
                err = max(err, h.error_rate * HOP_ATTENUATION)
                lat = max(lat, 1 + (h.latency_mult - 1) * HOP_ATTENUATION)
            elif h.status != "healthy" or h.lagging:
                lag = True
        memo[c] = Health(err, lat, lag)
        return memo[c]

    return {c: health(c) for c in components}


def symptom_alerts(health: dict[str, Health], customer_facing: set[str]) -> dict[str, dict]:
    """Alert rules: only customer-facing components alert."""
    out = {}
    for c in customer_facing:
        h = health[c]
        if h.error_rate >= ALERT_ERROR:
            out[c] = {"rule": "error_rate_high", "metric": "error_rate", "value": round(h.error_rate, 3),
                      "threshold": ALERT_ERROR}
        elif h.latency_mult >= ALERT_LATENCY_MULT:
            out[c] = {"rule": "latency_high", "metric": "p95_mult", "value": round(h.latency_mult, 2),
                      "threshold": ALERT_LATENCY_MULT}
    return out


# --- Chaos scenarios -------------------------------------------------------------

@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    root: str
    fault: Fault
    change: dict | None          # the real cause, if it is a change
    decoy: dict                  # red herring on a component off the dependency path
    remediation: str


# A scenario is world-agnostic: it names the component that will fault, the kind of change that
# causes it, and how the UI should describe it. The decoy is chosen at injection time from the
# seeded graph (a component no alerting service depends on), so a new world needs no new scenarios.
SCENARIO_SPECS = [
    {"id": "bad-deploy", "title": "Bad deploy", "root": "auth-service", "fault": Fault(0.42, 3.0),
     "change": {"kind": "deploy", "version": "v2.18.0", "risk": "high",
                "summary": "Switch token introspection to a new connection pool"},
     "remediation": "rollback"},
    {"id": "vendor-outage", "title": "Vendor outage", "root": "stripe", "fault": Fault(0.35, 4.0),
     "change": None, "remediation": "failover"},
    {"id": "flag-regression", "title": "Flag regression", "root": "risk-scoring", "fault": Fault(0.25, 5.0),
     "change": {"kind": "flag", "version": "risk.new-model-v3", "risk": "high",
                "summary": "Enable new risk model for 100% of traffic"},
     "remediation": "flag_off"},
    {"id": "db-migration-lock", "title": "Migration lock", "root": "postgres-ledger", "fault": Fault(0.5, 6.0),
     "change": {"kind": "migration", "version": "m-0450", "risk": "high",
                "summary": "Backfill a column on the ledger table"},
     "remediation": "rollback"},
]

DECOY_KINDS = ["config", "deploy", "flag"]


class WorldNotSeeded(RuntimeError):
    pass


def _world_name(g: Graph) -> str:
    hit = rows(g, "MATCH (w:World) RETURN w.name AS name LIMIT 1")
    if not hit:
        raise WorldNotSeeded("graph has no :World node; re-seed it with firebreak.seed --world <name>")
    return hit[0]["name"]


def _decoy(g: Graph, root: str, excluded: set[str], ts: int, seed_n: int) -> dict:
    """Pick a plausible recent change on a component no alerting service depends on."""
    candidates = rows(g, """
        MATCH (c:Component) WHERE c.kind <> 'vendor' AND c.kind <> 'cluster' AND NOT c.name IN $excluded
        OPTIONAL MATCH (caller:Component)-[:DEPENDS_ON*1..6]->(c)
        OPTIONAL MATCH (t:Team)-[:OWNS]->(c)
        OPTIONAL MATCH (p:Person)-[:MEMBER_OF]->(t)
        RETURN c.name AS component, count(DISTINCT caller) AS dependents, collect(DISTINCT p.id) AS members
        ORDER BY dependents ASC, c.name
        LIMIT 12
    """, {"excluded": sorted(excluded)})
    rng = random.Random(f"{root}:{seed_n}")
    pick = rng.choice(candidates) if candidates else {"component": root, "members": []}
    kind = rng.choice(DECOY_KINDS)
    return {"id": f"C-{7700 + seed_n}", "component": pick["component"], "kind": kind, "version": None,
            "author": rng.choice(pick["members"] or ["marcus"]), "risk": rng.choice(["high", "medium"]),
            "summary": f"{kind.capitalize()} on {pick['component']}", "minutes_ago": rng.randint(2, 6)}


KIND_PREFIX = {"deploy": "D", "flag": "F", "migration": "M", "config": "C"}


def scenarios(g: Graph) -> list[Scenario]:
    """Build the four chaos scenarios for whichever world this graph holds."""
    world = worlds.get(_world_name(g))
    roots = getattr(world, "SCENARIO_ROOTS", {})
    overrides = getattr(world, "SCENARIO_OVERRIDES", {})
    out = []
    for n, spec in enumerate(SCENARIO_SPECS):
        root = roots.get(spec["id"], spec["root"])
        ov = overrides.get(spec["id"], {})
        change = ov.get("change")
        if change is None and spec["change"]:
            kind = spec["change"]["kind"]
            author = rows(g, "MATCH (t:Team)-[:OWNS]->(:Component {name: $c}), (p:Person)-[:MEMBER_OF]->(t) "
                             "RETURN p.id AS id ORDER BY p.id LIMIT 1", {"c": root})
            change = {**spec["change"], "id": f"{KIND_PREFIX[kind]}-{4521 + n * 11}",
                      "author": author[0]["id"] if author else None, "minutes_ago": 8}
        title = ov.get("title", f"{spec['title']} on {root}")
        out.append(Scenario(spec["id"], title, root, spec["fault"], change, ov.get("decoy"), spec["remediation"]))
    return out


def scenario_map(g: Graph) -> dict[str, Scenario]:
    return {s.id: s for s in scenarios(g)}


# --- Graph I/O --------------------------------------------------------------------

def now_ms() -> int:
    return int(time.time() * 1000)


def load_topology(g: Graph) -> tuple[list[str], list[tuple[str, str, str]], dict[str, Fault], set[str]]:
    comps = rows(g, """
        MATCH (c:Component)
        RETURN c.name AS name, c.fault_error_rate AS fe, c.fault_latency_mult AS fl, c.customer_facing AS cf
    """)
    edges = rows(g, "MATCH (a:Component)-[r:DEPENDS_ON]->(b:Component) RETURN a.name AS a, b.name AS b, r.mode AS m")
    faults = {c["name"]: Fault(c["fe"], c["fl"] or 1.0) for c in comps if c["fe"] is not None}
    return ([c["name"] for c in comps], [(e["a"], e["b"], e["m"]) for e in edges], faults,
            {c["name"] for c in comps if c["cf"]})


def tick(g: Graph, ts: int | None = None) -> dict[str, str]:
    """One simulator step: recompute health from the graph and write it back.
    Opens alerts on newly failing symptoms, resolves alerts that cleared.
    Returns {component: status} for non-healthy components."""
    ts = ts or now_ms()
    names, edges, faults, facing = load_topology(g)
    health = propagate(names, edges, faults)
    g.query(
        """
        UNWIND $h AS h
        MATCH (c:Component {name: h.name})
        SET c.status = h.status, c.lagging = h.lag,
            c.error_rate = c.baseline_error_rate + h.err,
            c.p95_ms = toInteger(c.baseline_p95_ms * h.lat)
        """,
        {"h": [{"name": n, "status": h.status, "lag": h.lagging, "err": h.error_rate, "lat": h.latency_mult}
               for n, h in health.items()]},
    )

    alerts = symptom_alerts(health, facing)
    open_alerts = {r["c"] for r in rows(g, "MATCH (a:Alert {status: 'open'})-[:FIRED_ON]->(c) RETURN c.name AS c")}
    new = [{"component": c, **a} for c, a in alerts.items() if c not in open_alerts]
    if new:
        seq = rows(g, "MATCH (a:Alert) RETURN count(a) AS n")[0]["n"]
        for i, a in enumerate(new):
            a["id"] = f"ALR-{seq + i + 1:04d}"
        g.query(
            """
            UNWIND $alerts AS a
            MATCH (c:Component {name: a.component})
            CREATE (:Alert {id: a.id, rule: a.rule, metric: a.metric, value: a.value, threshold: a.threshold,
                            severity: CASE WHEN c.tier = 1 THEN 'critical' ELSE 'warning' END,
                            ts: $ts, status: 'open'})-[:FIRED_ON]->(c)
            """,
            {"alerts": new, "ts": ts},
        )
    g.query(
        """
        MATCH (a:Alert {status: 'open'})-[:FIRED_ON]->(c:Component)
        WHERE NOT c.name IN $alerting
        SET a.status = 'resolved', a.resolved_at = $ts
        """,
        {"alerting": list(alerts), "ts": ts},
    )
    return {n: h.status for n, h in health.items() if h.status != "healthy"}


def _next_id(g: Graph, base: str) -> str:
    """Scenario change ids are stable (D-4521) on first injection, suffixed on repeats."""
    existing = {r["id"] for r in rows(g, "MATCH (c:Change) WHERE c.id STARTS WITH $b RETURN c.id AS id", {"b": base})}
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def _create_change(g: Graph, spec: dict, component: str, ts: int) -> str:
    cid = _next_id(g, spec["id"])
    g.query(
        """
        MATCH (c:Component {name: $component}), (p:Person {id: $author})
        CREATE (p)-[:AUTHORED]->(:Change {id: $id, kind: $kind, version: $version, summary: $summary,
                                          risk: $risk, ts: $ts, scenario: true})-[:CHANGED]->(c)
        """,
        {"component": component, "author": spec["author"], "id": cid, "kind": spec["kind"],
         "version": spec["version"], "summary": spec["summary"], "risk": spec["risk"], "ts": ts},
    )
    return cid


def inject(g: Graph, scenario_id: str, with_decoy: bool = True, ts: int | None = None) -> dict:
    return inject_scenario(g, scenario_map(g)[scenario_id], with_decoy, ts)


def inject_scenario(g: Graph, s: Scenario, with_decoy: bool = True, ts: int | None = None) -> dict:
    ts = ts or now_ms()
    out = {"scenario": s.id, "root": s.root, "change": None, "decoy": None}
    if s.change:
        out["change"] = _create_change(g, s.change, s.root, ts - s.change["minutes_ago"] * MIN)
    if with_decoy and s.decoy:
        out["decoy"] = _create_change(g, s.decoy, s.decoy["component"], ts - s.decoy["minutes_ago"] * MIN)
    elif with_decoy:
        names, edges, _, facing = load_topology(g)
        alerting = symptom_alerts(propagate(names, edges, {s.root: s.fault}), facing)
        explained = set(alerting) | {s.root}
        for a in alerting:
            stack = [a]
            while stack:
                cur = stack.pop()
                explained.add(cur)
                stack += [b for s0, b, _ in edges if s0 == cur and b not in explained]
        # crc32, not hash(): hash() is salted per process, which made decoys differ between runs.
        decoy = _decoy(g, s.root, explained, ts, zlib.crc32(s.id.encode()) % 1000)
        s = replace(s, decoy=decoy)
        out["decoy"] = _create_change(g, decoy, decoy["component"], ts - decoy["minutes_ago"] * MIN)
    g.query(
        """
        MATCH (c:Component {name: $root})
        SET c.fault_error_rate = $e, c.fault_latency_mult = $l, c.fault_scenario = $sid, c.fault_change = $chg
        """,
        {"root": s.root, "e": s.fault.error_rate, "l": s.fault.latency_mult, "sid": s.id, "chg": out["change"]},
    )
    out["unhealthy"] = tick(g, ts)
    return out


def clear_fault(g: Graph, component: str) -> dict[str, str]:
    """Remediation: clear the fault on a component and revert the change that caused it."""
    g.query(
        """
        MATCH (c:Component {name: $name})
        OPTIONAL MATCH (ch:Change {id: c.fault_change})
        SET ch.reverted_at = $ts
        REMOVE c.fault_error_rate, c.fault_latency_mult, c.fault_scenario, c.fault_change
        """,
        {"name": component, "ts": now_ms()},
    )
    return tick(g)


def reset(g: Graph) -> dict[str, str]:
    """Clear every fault and return the world to green. Incidents and memory are kept;
    open scenario changes are marked reverted so they don't leak into the next run."""
    g.query("""
        MATCH (c:Component) WHERE c.fault_error_rate IS NOT NULL
        REMOVE c.fault_error_rate, c.fault_latency_mult, c.fault_scenario, c.fault_change
    """)
    g.query("MATCH (ch:Change {scenario: true}) WHERE ch.reverted_at IS NULL SET ch.reverted_at = $ts",
            {"ts": now_ms()})
    return tick(g)
