"""Public demo mode: each visitor works in a private copy of the graph. Needs FalkorDB."""

import pytest

from firebreak import public
from firebreak import simulator as sim
from firebreak.db import client, rows
from firebreak.seed import seed

try:
    client().list_graphs()
    LIVE = True
except Exception:
    LIVE = False

pytestmark = pytest.mark.skipif(not LIVE, reason="FalkorDB not reachable")


@pytest.fixture
def templates(monkeypatch):
    # Isolated template names so the demo graphs are untouched.
    monkeypatch.setattr(public, "template", lambda w: f"fb_pubtest_{w}")
    monkeypatch.setattr(public, "MAX_SANDBOXES", 2)
    public._sandboxes.clear()
    public._hits.clear()
    t = seed("pubtest_nimbuspay", "nimbuspay")
    yield t
    db = client()
    for n in [g for g in db.list_graphs() if g.startswith(public.PREFIX) or g.startswith("fb_pubtest_")]:
        db.select_graph(n).delete()
    public._sandboxes.clear()


def test_visitors_get_isolated_copies_and_template_stays_clean(templates):
    a = public.ensure_sandbox("a" * 16, "1.1.1.1", "nimbuspay")
    b = public.ensure_sandbox("b" * 16, "2.2.2.2", "nimbuspay")
    assert a != b
    ga, gb = client().select_graph(a), client().select_graph(b)
    sim.inject(ga, "bad-deploy")
    unhealthy = "MATCH (c:Component) WHERE c.status <> 'healthy' RETURN count(c) AS n"
    assert rows(ga, unhealthy)[0]["n"] > 0
    assert rows(gb, unhealthy)[0]["n"] == 0
    assert rows(templates, unhealthy)[0]["n"] == 0
    # Same session, same sandbox.
    assert public.ensure_sandbox("a" * 16, "1.1.1.1", "nimbuspay") == a


def test_sandbox_cap_evicts_least_recently_used(templates):
    for sid in ("c" * 16, "d" * 16, "e" * 16):
        public.ensure_sandbox(sid, "3.3.3.3", "nimbuspay")
    names = [g for g in client().list_graphs() if g.startswith(public.PREFIX)]
    assert len(names) == 2 and public.sandbox_name("c" * 16, "nimbuspay") not in names


def test_rate_limit_blocks_bursts():
    public._hits.clear()
    for _ in range(public.RULES["inject"][0]):
        public.check_rate("9.9.9.9", "POST", "/api/chaos/inject")
    with pytest.raises(public.Limited):
        public.check_rate("9.9.9.9", "POST", "/api/chaos/inject")
    public.check_rate("9.9.9.9", "GET", "/api/topology")  # reads are not limited
    public._hits.clear()
