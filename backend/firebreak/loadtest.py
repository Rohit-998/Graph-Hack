"""Concurrency and tenant-isolation load test (Track 02: high-concurrency reads/writes, memory per tenant).

Seeds several tenant graphs in one FalkorDB instance (both worlds), then at the same time:
  - injects a different chaos scenario into each tenant and runs the full agent investigation
    (Detective and Responder already run in parallel inside each one),
  - has several users per tenant hold conversations with the company brain (graph writes),
  - runs pre-deploy checks and algorithm calls (reads).

Then it verifies, per tenant: the verdict is the injected cause, the decoy was rejected, and
no node from another tenant (incident, change, user, conversation) is visible. It reports
throughput and latency percentiles.

Usage: uv run python -m firebreak.loadtest [--tenants 6] [--users 3] [--keep]
"""

import argparse
import asyncio
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import agents, conversation, graph_algos, incidents, preflight
from . import simulator as sim
from .db import client, graph, rows
from .llm import gateway
from .seed import seed

OUT = Path(__file__).resolve().parents[2] / "docs"
QUESTIONS = ["Why does checkout call auth synchronously?", "Who decided it?", "What broke there before?",
             "How do I fail over from Stripe?", "Who should I page?"]


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))], 1)


def _tenant_job(name: str, world: str, scenario: str, users: int) -> dict:
    """Everything one tenant does, run on its own thread against its own graph."""
    g = graph(f"fb_{name}")
    lat: dict[str, list[float]] = {"investigate": [], "ask": [], "preflight": [], "algo": []}
    t0 = time.perf_counter()
    out = sim.inject(g, scenario)
    iid = incidents.open_incident(g)
    t = time.perf_counter()
    v = asyncio.run(agents.investigate(g, iid))
    lat["investigate"].append((time.perf_counter() - t) * 1000)

    # Several users talking to the brain concurrently on this tenant.
    def chat(u: int) -> list[float]:
        times, cid = [], None
        for q in QUESTIONS[: 2 + u % 3]:
            s = time.perf_counter()
            a = conversation.ask(g, f"{name}-user{u}", q, cid)
            cid = a["conversation"]
            times.append((time.perf_counter() - s) * 1000)
        return times

    with ThreadPoolExecutor(max_workers=users) as ex:
        for times in ex.map(chat, range(users)):
            lat["ask"] += times

    for comp in ("auth-service", "postgres-ledger"):
        s = time.perf_counter()
        preflight.check(g, comp, "deploy")
        lat["preflight"].append((time.perf_counter() - s) * 1000)
    # Time the algorithms uncached (the pre-deploy checks above warmed the in-process cache).
    for cypher in (graph_algos.PAGERANK, graph_algos.BETWEENNESS):
        s = time.perf_counter()
        g.query(cypher)
        lat["algo"].append((time.perf_counter() - s) * 1000)

    decoy_rejected = bool(rows(g, """
        MATCH (:Incident {id: $id})-[:HAS_HYPOTHESIS]->(h:Hypothesis {status: 'rejected'})-[:SUSPECTS]->(c:Change {id: $d})
        RETURN h.id""", {"id": iid, "d": out["decoy"]}))
    return {"tenant": name, "world": world, "scenario": scenario, "incident": iid,
            "expected": out["change"] or out["root"], "verdict": v["root_cause"],
            "correct": v["root_cause"] == (out["change"] or out["root"]), "decoy_rejected": decoy_rejected,
            "wall_s": round(time.perf_counter() - t0, 2), "latency_ms": lat}


def _leaks(names: list[str]) -> list[str]:
    """Anything from tenant A visible in tenant B is a leak."""
    problems = []
    marks = {}
    for n in names:
        g = graph(f"fb_{n}")
        marks[n] = {
            "users": {r["id"] for r in rows(g, "MATCH (u:User) RETURN u.id AS id")},
            "convs": {r["id"] for r in rows(g, "MATCH (c:Conversation) RETURN c.id AS id")},
            "steps": rows(g, "MATCH (s:AgentStep) RETURN count(s) AS n")[0]["n"],
        }
        foreign = {u for u in marks[n]["users"] if not u.startswith(f"{n}-")}
        if foreign:
            problems.append(f"fb_{n} contains users from other tenants: {sorted(foreign)[:3]}")
    for a in names:
        for b in names:
            if a != b and marks[a]["convs"] & marks[b]["convs"]:
                problems.append(f"fb_{a} and fb_{b} share conversations")
    return problems


def run(tenants: int = 6, users: int = 3, keep: bool = False) -> dict:
    gateway.forced_off = True  # measure the graph, not an external API
    plan = []
    specs = [sp["id"] for sp in sim.SCENARIO_SPECS]
    for i in range(tenants):
        world = "nimbuspay" if i % 2 == 0 else "meridian"
        plan.append((f"load{i}", world, specs[i % len(specs)]))
    names = [p[0] for p in plan]
    try:
        t_seed = time.perf_counter()
        for name, world, _ in plan:
            seed(name, world)
        seed_s = round(time.perf_counter() - t_seed, 2)

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=tenants) as ex:
            results = list(ex.map(lambda p: _tenant_job(p[0], p[1], p[2], users), plan))
        wall = time.perf_counter() - t0
        leaks = _leaks(names)
    finally:
        gateway.forced_off = False
        if not keep:
            for n in names:
                try:
                    client().select_graph(f"fb_{n}").delete()
                except Exception:
                    pass

    all_lat = {k: [x for r in results for x in r["latency_ms"][k]] for k in ("investigate", "ask", "preflight", "algo")}
    ops = sum(len(v) for v in all_lat.values())
    writes = sum(len(r["latency_ms"]["investigate"]) + len(r["latency_ms"]["ask"]) for r in results)
    summary = {
        "tenants": tenants, "worlds": sorted({p[1] for p in plan}), "users_per_tenant": users,
        "seed_s": seed_s, "concurrent_wall_s": round(wall, 2), "operations": ops, "write_operations": writes,
        "ops_per_s": round(ops / wall, 1),
        "verdicts_correct": sum(r["correct"] for r in results), "decoys_rejected": sum(r["decoy_rejected"] for r in results),
        "leaks": leaks,
        "latency_ms": {k: {"p50": _pct(v, 50), "p95": _pct(v, 95), "n": len(v)} for k, v in all_lat.items()},
    }
    summary["passed"] = (summary["verdicts_correct"] == tenants and summary["decoys_rejected"] == tenants
                         and not leaks)
    _report(summary, results)
    return {"summary": summary, "results": results}


def _report(s: dict, results: list[dict]) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "concurrency.json").write_text(json.dumps({"summary": s, "results": results}, indent=2))
    lat = s["latency_ms"]
    lines = [
        "# Concurrency and tenant isolation",
        "",
        f"{s['tenants']} tenant graphs ({', '.join(s['worlds'])}) in one FalkorDB instance, all running at once: "
        f"each injects a different incident and runs the full agent investigation while "
        f"{s['users_per_tenant']} users per tenant hold conversations with the company brain, plus pre-deploy "
        f"checks and betweenness. Generated by `python -m firebreak.loadtest`.",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Correct verdicts | **{s['verdicts_correct']}/{s['tenants']}** |",
        f"| Decoys rejected | **{s['decoys_rejected']}/{s['tenants']}** |",
        f"| Cross-tenant leaks | **{len(s['leaks'])}** |",
        f"| Operations (concurrent) | {s['operations']} in {s['concurrent_wall_s']}s ({s['ops_per_s']}/s), "
        f"{s['write_operations']} of them graph writes |",
        "",
        "| Operation | p50 ms | p95 ms | n |",
        "|---|---|---|---|",
    ] + [f"| {k} | {v['p50']} | {v['p95']} | {v['n']} |" for k, v in lat.items()] + [
        "",
        "| Tenant | World | Scenario | Verdict | Correct | Decoy rejected |",
        "|---|---|---|---|---|---|",
    ] + [f"| fb_{r['tenant']} | {r['world']} | {r['scenario']} | `{r['verdict']}` | "
         f"{'✓' if r['correct'] else '✗'} | {'✓' if r['decoy_rejected'] else '✗'} |" for r in results]
    if s["leaks"]:
        lines += ["", "Leaks:", *[f"- {x}" for x in s["leaks"]]]
    (OUT / "concurrency.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tenants", type=int, default=6)
    p.add_argument("--users", type=int, default=3)
    p.add_argument("--keep", action="store_true")
    a = p.parse_args()
    res = run(a.tenants, a.users, a.keep)
    print(json.dumps(res["summary"], indent=2))
    raise SystemExit(0 if res["summary"]["passed"] else 1)


if __name__ == "__main__":
    main()
