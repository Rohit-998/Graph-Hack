"""Seed the tenant graph with the synthetic NimbusPay world.

Usage: uv run python -m firebreak.seed [--tenant nimbuspay]

Seeding drops and recreates the tenant graph, so it is idempotent: running it
twice gives the same graph (timestamps are relative to "now").
"""

import argparse
import random
import time

from falkordb import Graph

from . import seed_data as D
from .db import client

# Labels cannot be query parameters in Cypher, so components are created per kind.
COMPONENT_KINDS = ("Service", "Datastore", "Queue", "Vendor", "Cluster")


def now_ms() -> int:
    return int(time.time() * 1000)


def create_indexes(g: Graph) -> None:
    range_indexes = [
        ("Component", "name"), ("Person", "id"), ("Team", "name"), ("Customer", "id"),
        ("Product", "name"), ("Change", "id"), ("Change", "ts"), ("Incident", "id"),
        ("Alert", "id"), ("Decision", "id"), ("Runbook", "id"), ("Thread", "id"),
        ("Hypothesis", "id"), ("Action", "id"), ("AgentStep", "id"),
    ]
    for label, prop in range_indexes:
        g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")

    fulltext = {
        "Decision": ["title", "context", "decision", "consequences"],
        "Runbook": ["title", "body"],
        "Thread": ["title", "body"],
        "Incident": ["title", "summary"],
    }
    for label, props in fulltext.items():
        args = ", ".join(f"'{p}'" for p in props)
        g.query(f"CALL db.idx.fulltext.createNodeIndex('{label}', {args})")

    # 384-d embeddings (bge-small) for similar-incident recall.
    g.query(
        "CREATE VECTOR INDEX FOR (i:Incident) ON (i.embedding) "
        "OPTIONS {dimension: 384, similarityFunction: 'cosine'}"
    )


def seed_org(g: Graph, now: int) -> None:
    g.query(
        "UNWIND $teams AS t CREATE (:Team {name: t[0], slack_channel: t[1], mission: t[2]})",
        {"teams": [list(t) for t in D.TEAMS]},
    )
    people = [
        {"id": p[0], "name": p[1], "title": p[2], "timezone": p[3], "team": p[4], "role": p[5]}
        for p in D.PEOPLE
    ]
    g.query(
        "UNWIND $people AS p CREATE (:Person {id: p.id, name: p.name, title: p.title, timezone: p.timezone})",
        {"people": people},
    )
    g.query(
        """
        UNWIND $people AS p
        MATCH (person:Person {id: p.id}), (t:Team {name: p.team})
        CREATE (person)-[:MEMBER_OF {role: p.role}]->(t)
        """,
        {"people": [p for p in people if p["team"]]},
    )

    # Members report to their team lead; leads report to the VP.
    leads = {p["team"]: p["id"] for p in people if p["role"] == "lead"}
    vp = next(p["id"] for p in people if p["team"] is None)
    reports = [
        [p["id"], leads[p["team"]] if p["role"] == "member" else vp]
        for p in people if p["team"]
    ]
    g.query(
        """
        UNWIND $reports AS r
        MATCH (a:Person {id: r[0]}), (b:Person {id: r[1]})
        CREATE (a)-[:REPORTS_TO]->(b)
        """,
        {"reports": reports},
    )

    rotation = []
    for team, (primary, secondary) in D.ON_CALL.items():
        rotation.append([primary, team, 1])
        rotation.append([secondary, team, 2])
    g.query(
        """
        UNWIND $rotation AS r
        MATCH (p:Person {id: r[0]}), (t:Team {name: r[1]})
        CREATE (p)-[:ON_CALL {level: r[2], from: $from, until: $until}]->(t)
        """,
        {"rotation": rotation, "from": now - 3 * D.DAY, "until": now + 4 * D.DAY},
    )


def seed_topology(g: Graph) -> None:
    for kind in COMPONENT_KINDS:
        comps = []
        for name, k, tier, team, lang, desc, facing in D.COMPONENTS:
            if k != kind:
                continue
            p95, err, rps = D.BASELINE[tier]
            comps.append({
                "name": name, "tier": tier, "team": team, "language": lang, "description": desc,
                "customer_facing": facing, "p95": p95, "err": err, "rps": rps,
            })
        g.query(
            f"""
            UNWIND $comps AS c
            CREATE (n:Component:{kind} {{
                name: c.name, kind: '{kind.lower()}', tier: c.tier, language: c.language,
                description: c.description, customer_facing: c.customer_facing, status: 'healthy',
                baseline_p95_ms: c.p95, baseline_error_rate: c.err, baseline_rps: c.rps,
                p95_ms: c.p95, error_rate: c.err, rps: c.rps
            }})
            WITH n, c
            MATCH (t:Team {{name: c.team}})
            CREATE (t)-[:OWNS]->(n)
            """,
            {"comps": comps},
        )

    g.query(
        """
        UNWIND $deps AS d
        MATCH (a:Component {name: d[0]}), (b:Component {name: d[1]})
        CREATE (a)-[:DEPENDS_ON {mode: d[2], protocol: d[3]}]->(b)
        """,
        {"deps": [list(d) for d in D.DEPENDS_ON]},
    )
    g.query(
        """
        UNWIND $pairs AS p
        MATCH (a:Component {name: p[0]}), (b:Component {name: p[1]})
        CREATE (a)-[:FAILS_OVER_TO]->(b)
        """,
        {"pairs": [list(p) for p in D.FAILS_OVER_TO]},
    )
    placement = [
        [name, "k8s-prod-b" if name in D.RUNS_ON_B else "k8s-prod-a"]
        for name, kind, *_ in D.COMPONENTS
        if kind in ("Service", "Datastore", "Queue")
    ]
    g.query(
        """
        UNWIND $placement AS p
        MATCH (a:Component {name: p[0]}), (c:Cluster {name: p[1]})
        CREATE (a)-[:RUNS_ON]->(c)
        """,
        {"placement": placement},
    )


def seed_business(g: Graph) -> None:
    for name, desc, entries in D.PRODUCTS:
        g.query(
            """
            CREATE (p:Product {name: $name, description: $desc})
            WITH p
            UNWIND $entries AS e
            MATCH (c:Component {name: e})
            CREATE (p)-[:SERVED_BY]->(c)
            """,
            {"name": name, "desc": desc, "entries": entries},
        )
    for cid, name, tier, arr, sla, uses in D.CUSTOMERS:
        g.query(
            """
            CREATE (c:Customer {id: $id, name: $name, tier: $tier, arr_usd: $arr, sla_target: $sla})
            WITH c
            UNWIND $uses AS u
            MATCH (p:Product {name: u[0]})
            CREATE (c)-[:USES {gmv_per_hour_usd: u[1]}]->(p)
            """,
            {"id": cid, "name": name, "tier": tier, "arr": arr, "sla": sla,
             "uses": [[k, v] for k, v in uses.items()]},
        )


def seed_knowledge(g: Graph, now: int) -> None:
    for t in D.THREADS:
        g.query(
            """
            MATCH (author:Person {id: $author})
            CREATE (author)-[:POSTED]->(th:Thread {id: $id, channel: $channel, title: $title,
                                                   body: $body, ts: $ts})
            WITH th
            UNWIND $mentions AS m
            MATCH (c:Component {name: m})
            CREATE (th)-[:MENTIONS]->(c)
            """,
            {**{k: t[k] for k in ("id", "channel", "title", "body", "author", "mentions")},
             "ts": now - t["days_ago"] * D.DAY},
        )
    for d in D.DECISIONS:
        g.query(
            """
            CREATE (d:Decision {id: $id, title: $title, status: $status, date: $date,
                                context: $context, decision: $decision, consequences: $consequences})
            WITH d
            UNWIND $about AS a
            MATCH (c:Component {name: a})
            CREATE (d)-[:ABOUT]->(c)
            """,
            {**{k: d[k] for k in ("id", "title", "status", "context", "decision", "consequences", "about")},
             "date": now - d["days_ago"] * D.DAY},
        )
        g.query(
            """
            MATCH (d:Decision {id: $id})
            UNWIND $people AS pid
            MATCH (p:Person {id: pid})
            CREATE (p)-[:DECIDED]->(d)
            """,
            {"id": d["id"], "people": d["decided_by"]},
        )
        g.query(
            """
            MATCH (d:Decision {id: $id})
            UNWIND $threads AS tid
            MATCH (t:Thread {id: tid})
            CREATE (d)-[:DISCUSSED_IN]->(t)
            """,
            {"id": d["id"], "threads": d["threads"]},
        )
    for r in D.RUNBOOKS:
        g.query(
            """
            MATCH (w:Person {id: $wrote})
            CREATE (w)-[:WROTE]->(rb:Runbook {id: $id, title: $title, body: $body})
            WITH rb
            UNWIND $covers AS cname
            MATCH (c:Component {name: cname})
            CREATE (rb)-[:COVERS]->(c)
            """,
            {k: r[k] for k in ("id", "title", "body", "covers", "wrote")},
        )
    g.query(
        """
        UNWIND $experts AS e
        MATCH (p:Person {id: e[0]}), (c:Component {name: e[1]})
        CREATE (p)-[:EXPERT_IN {score: e[2], updated_at: $now}]->(c)
        """,
        {"experts": [list(e) for e in D.EXPERT_IN], "now": now},
    )


def _team_members() -> dict[str, list[str]]:
    members: dict[str, list[str]] = {}
    for pid, _, _, _, team, _ in D.PEOPLE:
        if team:
            members.setdefault(team, []).append(pid)
    return members


def seed_background_changes(g: Graph, now: int) -> None:
    """Routine changes over the last 90 days. None land in the last 2 days,
    so they never compete with chaos-scenario changes."""
    rng = random.Random(42)
    members = _team_members()
    changeable = [(n, team) for n, kind, _, team, *_ in D.COMPONENTS if kind not in ("Vendor", "Cluster")]
    changes = []
    for i in range(D.BACKGROUND_CHANGE_COUNT):
        comp, team = rng.choice(changeable)
        kind = rng.choice(D.CHANGE_KINDS)
        changes.append({
            "id": f"C-{3000 + i}",
            "kind": kind,
            "version": f"v{rng.randint(1, 9)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}" if kind == "deploy" else None,
            "summary": f"Routine {kind} on {comp}",
            "risk": rng.choice(["low", "low", "medium"]),
            "ts": now - rng.randint(2 * D.DAY, 90 * D.DAY),
            "component": comp,
            "author": rng.choice(members[team]),
        })
    g.query(
        """
        UNWIND $changes AS ch
        MATCH (c:Component {name: ch.component}), (p:Person {id: ch.author})
        CREATE (p)-[:AUTHORED]->(x:Change {id: ch.id, kind: ch.kind, version: ch.version,
                                           summary: ch.summary, risk: ch.risk, ts: ch.ts})-[:CHANGED]->(c)
        """,
        {"changes": changes},
    )


def seed_incidents(g: Graph, now: int) -> None:
    for n, inc in enumerate(D.INCIDENTS):
        started = now - inc["days_ago"] * D.DAY
        mitigated = started + inc["ttm_min"] * D.MIN
        g.query(
            """
            CREATE (i:Incident {id: $id, title: $title, summary: $summary, severity: $sev,
                                status: 'resolved', started_at: $started, identified_at: $identified,
                                mitigated_at: $mitigated, resolved_at: $resolved})
            WITH i
            UNWIND $affected AS a
            MATCH (c:Component {name: a})
            CREATE (i)-[:AFFECTED {impact: 'degraded'}]->(c)
            """,
            {"id": inc["id"], "title": inc["title"], "summary": inc["summary"], "sev": inc["severity"],
             "started": started, "identified": started + (inc["ttm_min"] * D.MIN) // 2,
             "mitigated": mitigated, "resolved": mitigated + 20 * D.MIN, "affected": inc["affected"]},
        )
        # The symptom alert fires on the most customer-facing affected component.
        g.query(
            """
            MATCH (i:Incident {id: $id}), (c:Component {name: $on})
            CREATE (i)-[:TRIGGERED_BY]->(a:Alert {id: $alert, rule: 'error_rate_high', metric: 'error_rate',
                                                   value: 0.12, threshold: 0.05, severity: 'critical',
                                                   ts: $ts, status: 'resolved'})-[:FIRED_ON]->(c)
            """,
            {"id": inc["id"], "on": inc["affected"][-1], "alert": f"ALR-H{n:03d}", "ts": started},
        )

        root = inc["root"]
        if root[0] == "change":
            _, comp, kind, version, summary, author = root
            g.query(
                """
                MATCH (i:Incident {id: $id}), (c:Component {name: $comp}), (p:Person {id: $author})
                CREATE (p)-[:AUTHORED]->(ch:Change {id: $cid, kind: $kind, version: $version,
                                                    summary: $summary, risk: 'high', ts: $ts})-[:CHANGED]->(c)
                CREATE (i)-[:ROOT_CAUSE {confidence: 1.0}]->(ch)
                """,
                {"id": inc["id"], "comp": comp, "author": author, "cid": f"D-{4000 + n}", "kind": kind,
                 "version": version, "summary": summary, "ts": started - 4 * D.MIN},
            )
        else:
            g.query(
                """
                MATCH (i:Incident {id: $id}), (c:Component {name: $comp})
                CREATE (i)-[:ROOT_CAUSE {confidence: 1.0}]->(c)
                """,
                {"id": inc["id"], "comp": root[1]},
            )

        g.query(
            """
            MATCH (i:Incident {id: $id})
            CREATE (i)-[:MITIGATED_BY]->(:Action {id: $aid, kind: $kind, target: $target, status: 'executed',
                                                  proposed_by: 'human', approved_by: $by, result: 'success'})
            WITH i
            UNWIND $responders AS r
            MATCH (p:Person {id: r})
            CREATE (p)-[:RESPONDED_TO]->(i)
            """,
            {"id": inc["id"], "aid": f"ACT-H{n:03d}", "kind": inc["action"], "target": root[1],
             "by": inc["responders"][0], "responders": inc["responders"]},
        )


def seed(tenant: str | None = None) -> Graph:
    from .config import settings

    name = f"fb_{tenant}" if tenant else settings.graph_name
    db = client()
    if name in db.list_graphs():
        db.select_graph(name).delete()
    g = db.select_graph(name)

    now = now_ms()
    create_indexes(g)
    seed_org(g, now)
    seed_topology(g)
    seed_business(g)
    seed_knowledge(g, now)
    seed_background_changes(g, now)
    seed_incidents(g, now)
    return g


def summary(g: Graph) -> list[tuple[str, int]]:
    res = g.query("MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) ORDER BY l")
    return [tuple(r) for r in res.result_set]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Firebreak demo graph")
    parser.add_argument("--tenant", default=None)
    args = parser.parse_args()
    t0 = time.perf_counter()
    g = seed(args.tenant)
    edges = g.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    print(f"Seeded graph '{g.name}' in {time.perf_counter() - t0:.2f}s")
    for label, count in summary(g):
        print(f"  {label:<12} {count}")
    print(f"  {'(edges)':<12} {edges}")


if __name__ == "__main__":
    main()
