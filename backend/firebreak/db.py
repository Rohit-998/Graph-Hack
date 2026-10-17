"""FalkorDB connection helpers."""

from functools import lru_cache

from falkordb import FalkorDB, Graph

from .config import settings


@lru_cache(maxsize=1)
def client() -> FalkorDB:
    return FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port)


# The graph the API and ticker work on. Switchable at runtime (one graph per tenant/world).
_active: dict[str, str | None] = {"name": None}


def active_graph_name() -> str:
    return _active["name"] or settings.graph_name


def set_active_graph(name: str) -> None:
    _active["name"] = name


def graph(name: str | None = None) -> Graph:
    return client().select_graph(name or active_graph_name())


def rows(g: Graph, cypher: str, params: dict | None = None) -> list[dict]:
    """Run a query and return rows as dicts keyed by column alias."""
    res = g.query(cypher, params or {})
    cols = [h[1] if isinstance(h, (list, tuple)) else h for h in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]
