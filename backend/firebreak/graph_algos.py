"""Graph algorithms as agent tools (PRD §9.7), run by FalkorDB itself.

  algo.pageRank('Component', 'DEPENDS_ON')          -> criticality
  algo.betweenness({nodeLabels, relationshipTypes}) -> single points of failure

A component whose removal sits on many dependency paths is a choke point:
losing it breaks unrelated parts of the graph at once. Scores are written back
to Component.page_rank / Component.betweenness so they are visible in the
Browser and usable in plain Cypher, and cached in-process for a short TTL
because the topology only changes when changes are injected.
"""

import time
from dataclasses import dataclass

from falkordb import Graph

PAGERANK = "CALL algo.pageRank('Component', 'DEPENDS_ON') YIELD node, score RETURN node.name AS name, score"
BETWEENNESS = """
CALL algo.betweenness({nodeLabels: ['Component'], relationshipTypes: ['DEPENDS_ON'],
                       samplingSize: 32, samplingSeed: 42})
YIELD node, score RETURN node.name AS name, score
"""

CACHE_TTL_S = 5.0


@dataclass
class Ranking:
    scores: dict[str, float]
    cypher: str
    duration_ms: float
    algorithm: str

    def top(self, n: int = 5) -> list[dict]:
        return [{"component": k, "score": round(v, 4)} for k, v in
                sorted(self.scores.items(), key=lambda kv: -kv[1])[:n]]

    def normalized(self) -> dict[str, float]:
        hi = max(self.scores.values(), default=0.0)
        return {k: (v / hi if hi else 0.0) for k, v in self.scores.items()}


_cache: dict[str, tuple[float, Ranking]] = {}


def _run(g: Graph, algo: str, cypher: str) -> Ranking:
    hit = _cache.get(f"{g.name}:{algo}")
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    t0 = time.perf_counter()
    res = g.query(cypher)
    scores = {r[0]: float(r[1] or 0.0) for r in res.result_set if r[0]}
    r = Ranking(scores, cypher.strip(), (time.perf_counter() - t0) * 1000, algo)
    _cache[f"{g.name}:{algo}"] = (time.time(), r)
    return r


def pagerank(g: Graph) -> Ranking:
    """Criticality: components that much of the graph depends on, Transitively weighted."""
    return _run(g, "pageRank", PAGERANK)


def betweenness(g: Graph) -> Ranking:
    """Single points of failure: components on the most shortest dependency paths."""
    return _run(g, "betweenness", BETWEENNESS)


def invalidate() -> None:
    _cache.clear()


def persist(g: Graph) -> dict:
    """Write both scores back onto Component nodes for inspection in the Browser."""
    pr, bw = pagerank(g), betweenness(g)
    g.query(
        """
        UNWIND $rows AS r
        MATCH (c:Component {name: r.name})
        SET c.page_rank = r.pr, c.betweenness = r.bw
        """,
        {"rows": [{"name": n, "pr": pr.scores.get(n, 0.0), "bw": bw.scores.get(n, 0.0)}
                  for n in set(pr.scores) | set(bw.scores)]},
    )
    return {"page_rank": pr.top(5), "betweenness": bw.top(5),
            "duration_ms": round(pr.duration_ms + bw.duration_ms, 2)}


def spof_scan(g: Graph, top: int = 5) -> list[dict]:
    """Rank choke points by betweenness, with the teams that own them and who is on call."""
    bw = betweenness(g)
    if not bw.scores:
        return []
    out = []
    for name, score in sorted(bw.scores.items(), key=lambda kv: -kv[1])[:top]:
        if score <= 0:
            continue
        info = g.query(
            """
            MATCH (c:Component {name: $name})<-[:OWNS]-(t:Team)
            OPTIONAL MATCH (c)<-[:DEPENDS_ON*1..6]-(up:Component)
            OPTIONAL MATCH (p:Person)-[:ON_CALL]->(t)
            RETURN t.name AS team, count(DISTINCT up) AS dependents, collect(DISTINCT p.name) AS on_call
            """,
            {"name": name},
        ).result_set
        team, dependents, on_call = (info[0][0], info[0][1], info[0][2]) if info else (None, 0, [])
        out.append({"component": name, "betweenness": round(score, 2), "team": team,
                    "dependents": dependents, "on_call": on_call})
    return out
