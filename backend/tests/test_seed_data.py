"""Referential integrity of the synthetic world. Runs without FalkorDB."""

from firebreak import seed_data as D

COMPONENTS = {c[0] for c in D.COMPONENTS}
PEOPLE = {p[0] for p in D.PEOPLE}
TEAMS = {t[0] for t in D.TEAMS}
PRODUCTS = {p[0] for p in D.PRODUCTS}
THREADS = {t["id"] for t in D.THREADS}


def test_sizes_match_prd():
    assert len(D.COMPONENTS) == 35
    assert len(D.TEAMS) == 6
    assert 18 <= len(D.PEOPLE) <= 20
    assert len(D.PRODUCTS) == 5
    assert len(D.CUSTOMERS) == 5
    assert len(D.INCIDENTS) == 15
    assert len(D.DECISIONS) == 5 and len(D.RUNBOOKS) == 5 and len(D.THREADS) == 8
    # ~80 changes: background + one per change-rooted incident
    rooted = sum(1 for i in D.INCIDENTS if i["root"][0] == "change")
    assert 75 <= D.BACKGROUND_CHANGE_COUNT + rooted <= 85


def test_unique_names():
    assert len(COMPONENTS) == len(D.COMPONENTS)
    assert len(PEOPLE) == len(D.PEOPLE)
    assert len({i["id"] for i in D.INCIDENTS}) == len(D.INCIDENTS)


def test_component_references():
    for c in D.COMPONENTS:
        assert c[3] in TEAMS, c
    for a, b, mode, _ in D.DEPENDS_ON:
        assert a in COMPONENTS and b in COMPONENTS, (a, b)
        assert mode in ("sync", "async")
    for _, _, entries in D.PRODUCTS:
        assert set(entries) <= COMPONENTS
    for d in D.DECISIONS:
        assert set(d["about"]) <= COMPONENTS
        assert set(d["decided_by"]) <= PEOPLE
        assert set(d["threads"]) <= THREADS
    for r in D.RUNBOOKS:
        assert set(r["covers"]) <= COMPONENTS and r["wrote"] in PEOPLE
    for t in D.THREADS:
        assert set(t["mentions"]) <= COMPONENTS and t["author"] in PEOPLE
    for pid, comp, _ in D.EXPERT_IN:
        assert pid in PEOPLE and comp in COMPONENTS


def test_people_and_oncall():
    for p in D.PEOPLE:
        assert p[4] is None or p[4] in TEAMS
    assert set(D.ON_CALL) == TEAMS
    for primary, secondary in D.ON_CALL.values():
        assert primary in PEOPLE and secondary in PEOPLE
    # every team has exactly one lead
    for team in TEAMS:
        assert sum(1 for p in D.PEOPLE if p[4] == team and p[5] == "lead") == 1


def test_customers_use_known_products():
    for c in D.CUSTOMERS:
        assert set(c[5]) <= PRODUCTS


def test_incidents():
    for inc in D.INCIDENTS:
        assert set(inc["affected"]) <= COMPONENTS
        assert set(inc["responders"]) <= PEOPLE
        assert inc["root"][1] in COMPONENTS
        if inc["root"][0] == "change":
            assert inc["root"][5] in PEOPLE


def test_dependency_graph_is_acyclic():
    adj: dict[str, list[str]] = {}
    for a, b, *_ in D.DEPENDS_ON:
        adj.setdefault(a, []).append(b)
    state: dict[str, int] = {}

    def visit(n: str) -> None:
        state[n] = 1
        for m in adj.get(n, []):
            assert state.get(m) != 1, f"cycle through {n} -> {m}"
            if m not in state:
                visit(m)
        state[n] = 2

    for n in adj:
        if n not in state:
            visit(n)
