"""FalkorDB connection helpers."""

from functools import lru_cache

from falkordb import FalkorDB, Graph

from .config import settings


@lru_cache(maxsize=1)
def client() -> FalkorDB:
    # Username/password/TLS are optional so local Docker keeps working unchanged;
    # FalkorDB Cloud needs credentials (its Free tier has no TLS).
    return FalkorDB(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        username=settings.falkordb_username,
        password=settings.falkordb_password,
        ssl=settings.falkordb_tls,
        socket_timeout=15,
        socket_connect_timeout=10,
        retry_on_timeout=True,
    )


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
