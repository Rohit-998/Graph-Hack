"""MCP server over a real stdio session. Skipped if FalkorDB is not reachable."""

import asyncio
import json
import os
import sys

import pytest

from firebreak.db import client

try:
    client().list_graphs()
    LIVE = True
except Exception:
    LIVE = False


@pytest.mark.skipif(not LIVE, reason="FalkorDB not reachable")
def test_mcp_lists_and_calls_tools():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from firebreak.seed import seed

    g = seed("mcptest")  # isolated tenant; the server is pointed at it via TENANT

    async def run():
        env = {**os.environ, "LLM_PROVIDER": "none", "TENANT": "mcptest"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "firebreak.mcp_server"], env=env)
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert {"rank_root_causes", "blast_radius", "who_knows", "similar_incidents"} <= names
            res = await s.call_tool("blast_radius", {"component": "auth-service"})
            data = json.loads(res.content[0].text)
            assert {"checkout-api", "payouts-api"} <= {u["component"] for u in data["upstream"]}

    try:
        asyncio.run(run())
    finally:
        g.delete()
