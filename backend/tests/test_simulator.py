"""Propagation and alert rules over the seeded topology. Runs without FalkorDB."""

import pytest

from firebreak import seed_data as D
from firebreak.simulator import SCENARIOS, Fault, propagate, symptom_alerts

NAMES = [c[0] for c in D.COMPONENTS]
EDGES = [(a, b, m) for a, b, m, _ in D.DEPENDS_ON]
FACING = {c[0] for c in D.COMPONENTS if c[6]}


def closure_from(start: str) -> set[str]:
    """Everything start (transitively) depends on."""
    out, stack = set(), [start]
    while stack:
        n = stack.pop()
        if n in out:
            continue
        out.add(n)
        stack += [b for a, b, _ in EDGES if a == n]
    return out


def test_all_healthy_without_faults():
    h = propagate(NAMES, EDGES, {})
    assert all(x.status == "healthy" for x in h.values())
    assert symptom_alerts(h, FACING) == {}


def test_bad_deploy_alerts_on_symptoms_not_cause():
    h = propagate(NAMES, EDGES, {"auth-service": Fault(0.42, 3.0)})
    alerts = symptom_alerts(h, FACING)
    assert set(alerts) == {"checkout-api", "payouts-api", "web-bff"}
    assert "auth-service" not in alerts
    assert h["auth-service"].status == "down"
    assert h["search-service"].status == "healthy"


def test_async_edges_only_lag():
    h = propagate(NAMES, EDGES, {"kafka-events": Fault(0.6, 5.0)})
    assert h["notifications-service"].status == "healthy"
    assert h["notifications-service"].lagging
    assert symptom_alerts(h, FACING) == {}


@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_every_scenario_alerts_and_decoy_is_off_path(sid):
    s = SCENARIOS[sid]
    h = propagate(NAMES, EDGES, {s.root: s.fault})
    alerts = symptom_alerts(h, FACING)
    assert alerts, f"{sid} raised no alerts"
    assert s.root not in alerts, f"{sid} alerts on the cause itself"
    # The root explains every alert; the decoy explains none.
    assert all(s.root in closure_from(a) for a in alerts)
    assert all(s.decoy["component"] not in closure_from(a) for a in alerts)
