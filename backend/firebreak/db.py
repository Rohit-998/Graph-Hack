"""FalkorDB connection helpers."""

from contextvars import ContextVar
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

# Per-request override (public demo: each visitor picks their own company without switching it
# for everyone). Set by API middleware; contextvars follow the request into worker threads.
_request_graph: ContextVar[str | None] = ContextVar("firebreak_request_graph", default=None)


def active_graph_name() -> str:
    return _request_graph.get() or _active["name"] or settings.graph_name


def use_graph_for_request(name: str | None):
    """Returns a token to reset the override with `_request_graph.reset(token)`."""
    return _request_graph.set(name)


def reset_request_graph(token) -> None:
    _request_graph.reset(token)


def set_active_graph(name: str) -> None:
    _active["name"] = name


def graph(name: str | None = None) -> Graph:
    return client().select_graph(name or active_graph_name())


def rows(g: Graph, cypher: str, params: dict | None = None) -> list[dict]:
    """Run a query and return rows as dicts keyed by column alias."""
    res = g.query(cypher, params or {})
    cols = [h[1] if isinstance(h, (list, tuple)) else h for h in res.header]
    return [dict(zip(cols, r)) for r in res.result_set]
