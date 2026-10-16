"""Headless CLI for the incident loop (PRD §17.1).

  uv run python -m firebreak.cli inject bad-deploy [--no-decoy]
  uv run python -m firebreak.cli investigate INC-2186
  uv run python -m firebreak.cli approve ACT-INC-2186-1
  uv run python -m firebreak.cli reset
  uv run python -m firebreak.cli acceptance      # the shippability gate, all scenarios
"""

import argparse
import asyncio
import json
import sys
import time

from . import agents, incidents
from . import simulator as sim
from .db import graph, rows
from .seed import seed


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


ACCEPTANCE_TENANT = "acceptance"


def acceptance(keep: bool = False) -> bool:
    """Inject every scenario with a decoy, investigate deterministically, approve the
    fix, and assert the verdict is correct and the world returns to green.

    Runs on its own tenant graph, so a live app (and its background ticker) on the
    demo graph can't race it for alerts."""
    from .llm import gateway

    gateway.forced_off = True  # the gate is graph-only by definition
    g = seed(ACCEPTANCE_TENANT)
    ok = True
    try:
        for s in sim.SCENARIOS.values():
            sim.inject(g, s.id, with_decoy=True)
            iid = incidents.open_incident(g)
            v = asyncio.run(agents.investigate(g, iid)) if iid else {"root_cause": None}
            expected = rows(g, "MATCH (c:Component {name: $n}) RETURN c.fault_change AS ch",
                            {"n": s.root})[0]["ch"] or s.root
            actions = v.get("actions") or []
            checks = {
                "incident opened": iid is not None,
                "root cause": v["root_cause"] == expected,
                "confidence > 70%": v.get("confidence", 0) > 0.7,
                "decoy rejected": bool(iid and rows(g, """
                    MATCH (:Incident {id: $id})-[:HAS_HYPOTHESIS]->(h:Hypothesis {status: 'rejected'})
                    RETURN h.id""", {"id": iid})),
                "remediation proposed": bool(actions) and actions[0]["kind"] == s.remediation,
            }
            if actions:
                t0 = time.perf_counter()
                incidents.approve_action(g, actions[0]["id"])
                unhealthy = rows(g, "MATCH (c:Component) WHERE c.status <> 'healthy' RETURN c.name AS n")
                checks["green after approve"] = not unhealthy and time.perf_counter() - t0 < 5
                checks["incident resolved"] = incidents.detail(g, iid)["status"] == "resolved"
            sim.reset(g)
            incidents.close_open(g, "acceptance")

            passed = all(checks.values())
            ok &= passed
            print(f"{'PASS' if passed else 'FAIL'}  {s.id:<18} {v.get('headline', 'no verdict')}")
            for name, good in checks.items():
                if not good:
                    print(f"      x {name}")
    finally:
        gateway.forced_off = False
        if not keep:
            g.delete()
    print("\nACCEPTANCE", "PASSED" if ok else "FAILED")
    return ok


def main() -> None:
    p = argparse.ArgumentParser(prog="firebreak")
    sub = p.add_subparsers(dest="cmd", required=True)
    inj = sub.add_parser("inject")
    inj.add_argument("scenario", choices=list(sim.SCENARIOS))
    inj.add_argument("--no-decoy", action="store_true")
    sub.add_parser("investigate").add_argument("incident")
    sub.add_parser("approve").add_argument("action")
    sub.add_parser("reset")
    acc = sub.add_parser("acceptance")
    acc.add_argument("--keep", action="store_true", help="keep the fb_acceptance graph for inspection")
    a = p.parse_args()

    if a.cmd == "acceptance":
        sys.exit(0 if acceptance(a.keep) else 1)
    g = graph()
    if a.cmd == "inject":
        out = sim.inject(g, a.scenario, not a.no_decoy)
        out["incident"] = incidents.open_incident(g)
        _print(out)
    elif a.cmd == "investigate":
        _print(asyncio.run(agents.investigate(g, a.incident)))
    elif a.cmd == "approve":
        _print(incidents.approve_action(g, a.action))
    elif a.cmd == "reset":
        _print({"unhealthy": sim.reset(g)})


if __name__ == "__main__":
    main()
