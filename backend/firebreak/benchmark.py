"""RCA benchmark (PRD FR-P1.7): Firebreak vs baselines on generated scenarios.

Scenarios are generated from the seeded topology, not hand-picked: for every
component whose fault reaches a customer-facing service, inject a fault (a
change, or a vendor outage), plus a decoy change on a component that no
alerting service depends on. Timings are random, so sometimes the real change
is the most recent one and sometimes the decoy is.

Methods
  firebreak        the full agent loop, graph only (zero LLM calls)
  most_recent      blame the most recent change in the window
  flat_llm         an LLM given the alerts and recent changes as a flat list,
                   with no dependency topology (optional, spends quota)

Usage: uv run python -m firebreak.benchmark [--n 16] [--llm-baseline] [--keep]
Runs on its own tenant graph (fb_bench) so the demo graph is untouched.
"""

import argparse
import asyncio
import json
import random
import statistics
import time
from pathlib import Path

from . import agents, incidents
from . import seed_data as D
from . import simulator as sim
from .db import client, rows
from .llm import gateway
from .seed import seed

TENANT = "bench"
OUT_DIR = Path(__file__).resolve().parents[2] / "docs"

KIND_BY_COMPONENT = {"Datastore": ["migration", "config"], "Queue": ["config"], "Service": ["deploy", "config", "flag"]}


def _closure(edges: list[tuple[str, str, str]], start: str) -> set[str]:
    out, stack = set(), [start]
    while stack:
        n = stack.pop()
        if n not in out:
            out.add(n)
            stack += [b for a, b, _ in edges if a == n]
    return out


def generate(n: int = 16, rng_seed: int = 7) -> list[sim.Scenario]:
    rng = random.Random(rng_seed)
    names = [c[0] for c in D.COMPONENTS]
    kind_of = {c[0]: c[1] for c in D.COMPONENTS}
    team_of = {c[0]: c[3] for c in D.COMPONENTS}
    facing = {c[0] for c in D.COMPONENTS if c[6]}
    edges = [(a, b, m) for a, b, m, _ in D.DEPENDS_ON]
    members: dict[str, list[str]] = {}
    for pid, _, _, _, team, _ in D.PEOPLE:
        if team:
            members.setdefault(team, []).append(pid)

    candidates = []
    for root in names:
        if root in facing or kind_of[root] == "Cluster":
            continue
        fault = sim.Fault(round(rng.uniform(0.3, 0.55), 2), round(rng.uniform(2.5, 5.0), 1))
        alerting = sim.symptom_alerts(sim.propagate(names, edges, {root: fault}), facing)
        if not alerting:
            continue
        explained = set().union(*(_closure(edges, a) for a in alerting))
        decoys = [c for c in names if c not in explained and kind_of[c] not in ("Vendor", "Cluster")]
        if not decoys:
            continue
        candidates.append((root, fault, decoys))

    rng.shuffle(candidates)
    out = []
    for i, (root, fault, decoys) in enumerate(candidates[:n]):
        decoy_comp = rng.choice(decoys)
        change = None
        if kind_of[root] != "Vendor":
            kind = rng.choice(KIND_BY_COMPONENT[kind_of[root]])
            change = {"id": f"B-{5000 + i}", "kind": kind, "version": f"v{rng.randint(1, 9)}.{rng.randint(0, 30)}.0",
                      "author": rng.choice(members[team_of[root]]), "risk": rng.choice(["high", "high", "medium"]),
                      "summary": f"Benchmark {kind} on {root}", "minutes_ago": rng.randint(3, 15)}
        dkind = rng.choice(KIND_BY_COMPONENT[kind_of[decoy_comp]])
        decoy = {"id": f"B-{6000 + i}", "component": decoy_comp, "kind": dkind, "version": None,
                 "author": rng.choice(members[team_of[decoy_comp]]), "risk": rng.choice(["high", "medium"]),
                 "summary": f"Benchmark {dkind} on {decoy_comp}", "minutes_ago": rng.randint(1, 12)}
        remediation = {"deploy": "rollback", "config": "rollback", "migration": "rollback",
                       "flag": "flag_off"}.get(change["kind"]) if change else "failover"
        out.append(sim.Scenario(f"bench-{i:02d}", f"{root} ({change['kind'] if change else 'vendor outage'})",
                                root, fault, change, decoy, remediation))
    return out


FLAT_SYSTEM = (
    "You are an SRE. Given the alerts and the recent changes, name the single most likely root cause. "
    "Return JSON only: {\"root_cause\": \"<change id, or a component name if no change caused it>\"}."
)


def _changes(g, now: int) -> list[dict]:
    return rows(g, """
        MATCH (ch:Change)-[:CHANGED]->(c:Component)
        WHERE ch.ts >= $since AND ch.reverted_at IS NULL
        RETURN ch.id AS id, c.name AS component, ch.kind AS kind, ch.summary AS summary, ch.risk AS risk, ch.ts AS ts
        ORDER BY ch.ts DESC
    """, {"since": now - 2 * 3_600_000})


def run(n: int = 16, llm_baseline: bool = False, keep: bool = False) -> dict:
    g = seed(TENANT)
    scenarios = generate(n)
    results = []
    try:
        for s in scenarios:
            out = sim.inject_scenario(g, s, with_decoy=True)
            expected = out["change"] or s.root
            iid = incidents.open_incident(g)
            alerting = incidents.alerting_components(g, iid)
            now = sim.now_ms()
            changes = _changes(g, now)

            gateway.forced_off = True
            t0 = time.perf_counter()
            v = asyncio.run(agents.investigate(g, iid))
            ttrc = time.perf_counter() - t0
            gateway.forced_off = False

            row = {
                "scenario": s.id, "title": s.title, "expected": expected, "decoy": out["decoy"],
                "decoy_more_recent": s.change is None or s.decoy["minutes_ago"] < s.change["minutes_ago"],
                "alerting": alerting,
                "firebreak": v["root_cause"], "firebreak_ok": v["root_cause"] == expected,
                "firebreak_confidence": v["confidence"], "firebreak_s": round(ttrc, 3),
                "most_recent": changes[0]["id"] if changes else None,
            }
            row["most_recent_ok"] = row["most_recent"] == expected
            row["most_recent_component"] = changes[0]["component"] if changes else None

            if llm_baseline:
                minutes = lambda ts: round((now - ts) / 60_000)  # noqa: E731
                prompt = json.dumps({
                    "alerts": [{"service": a, "rule": "error_rate_high"} for a in alerting],
                    "recent_changes": [{"id": c["id"], "component": c["component"], "kind": c["kind"],
                                        "summary": c["summary"], "risk": c["risk"],
                                        "minutes_ago": minutes(c["ts"])} for c in changes],
                })
                ans = None
                for _ in range(3):  # wait out the local rate limiter / a 429 instead of scoring a miss
                    ans = gateway.chat_json(FLAT_SYSTEM, prompt, max_tokens=60)
                    if ans is not None or gateway.usage.last_error not in ("local rate limit", "all keys cooling down"):
                        break
                    time.sleep(20)
                row["flat_llm"] = ans and str(ans.get("root_cause", "")).strip()
                row["flat_llm_error"] = None if ans else gateway.usage.last_error
                # Lenient: naming the right component counts, even without the change id.
                row["flat_llm_ok"] = row["flat_llm"] in (expected, s.root)
            results.append(row)
            sim.reset(g)
            incidents.close_open(g, "benchmark")
            print(f"{'PASS' if row['firebreak_ok'] else 'FAIL'}  {s.id}  {s.title:<40} "
                  f"firebreak={row['firebreak']}  most_recent={row['most_recent']}"
                  + (f"  flat_llm={row['flat_llm']}" if llm_baseline else ""))
    finally:
        gateway.forced_off = False
        if not keep:
            g.delete()

    summary = summarize(results, llm_baseline)
    write_report(results, summary, llm_baseline)
    return {"summary": summary, "results": results}


def summarize(results: list[dict], llm_baseline: bool) -> dict:
    n = len(results)
    acc = lambda key: round(sum(r[key] for r in results) / n, 3) if n else 0  # noqa: E731
    out = {
        "scenarios": n,
        "decoy_more_recent": sum(r["decoy_more_recent"] for r in results),
        "firebreak_top1": acc("firebreak_ok"),
        "most_recent_top1": acc("most_recent_ok"),
        "firebreak_median_s": round(statistics.median(r["firebreak_s"] for r in results), 3) if n else None,
        "firebreak_llm_calls": 0,
    }
    if llm_baseline:
        out["flat_llm_top1"] = acc("flat_llm_ok")
        out["flat_llm_model"] = gateway.model
    return out


def write_report(results: list[dict], summary: dict, llm_baseline: bool) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "benchmark.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    pct = lambda x: f"{x * 100:.0f}%"  # noqa: E731
    lines = [
        "# RCA benchmark",
        "",
        f"{summary['scenarios']} scenarios generated from the NimbusPay topology (`firebreak/benchmark.py`, seed 7). "
        f"Each has one real cause and one decoy change on a component no alerting service depends on. "
        f"In {summary['decoy_more_recent']} of them the decoy is more recent than the real cause (or the cause "
        f"is a vendor outage with no change at all).",
        "",
        "| Method | Top-1 accuracy | LLM calls / incident |",
        "|---|---|---|",
        f"| **Firebreak** (graph RCA, deterministic) | **{pct(summary['firebreak_top1'])}** | 0 |",
        f"| Most recent change | {pct(summary['most_recent_top1'])} | 0 |",
    ]
    if llm_baseline:
        lines.append(f"| Flat-context LLM ({summary['flat_llm_model']}, no topology) | "
                     f"{pct(summary['flat_llm_top1'])} | 1 |")
        lines += ["", "The flat-LLM baseline is scored leniently: naming the right component counts as correct "
                      "even without the change id. It sees the same alerts and changes Firebreak does, "
                      "but not the dependency graph."]
    lines += [
        "",
        f"Median Firebreak time to verdict: {summary['firebreak_median_s']}s (full agent loop, incl. graph writes).",
        "",
        "| Scenario | Real cause | Decoy | Firebreak | Most recent" + (" | Flat LLM |" if llm_baseline else " |"),
        "|---|---|---|---|---" + ("|---|" if llm_baseline else "|"),
    ]
    mark = lambda ok: "✓" if ok else "✗"  # noqa: E731
    for r in results:
        line = (f"| {r['title']} | `{r['expected']}` | `{r['decoy']}` | {mark(r['firebreak_ok'])} "
                f"{r['firebreak_confidence']:.0%} | {mark(r['most_recent_ok'])} `{r['most_recent']}`")
        if llm_baseline:
            line += f" | {mark(r['flat_llm_ok'])} `{r['flat_llm']}`"
        lines.append(line + " |")
    lines += ["", "Weights were set before the benchmark was written and were not tuned against it."]
    (OUT_DIR / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=16)
    p.add_argument("--llm-baseline", action="store_true", help="also run the flat-context LLM baseline")
    p.add_argument("--keep", action="store_true", help="keep the fb_bench graph afterwards")
    a = p.parse_args()
    if client() is None:
        raise SystemExit("FalkorDB not reachable")
    res = run(a.n, a.llm_baseline, a.keep)
    print("\n" + json.dumps(res["summary"], indent=2))


if __name__ == "__main__":
    main()
