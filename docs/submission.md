# Submission checklist

Graph Hacks: Context for AI Agents (WeMakeDevs × FalkorDB). Deadline **Oct 18, 2026, 11:59 PM IST**.
Mirrors PRD §18. Status as of Oct 17.

## Required

| Requirement | Status | Where / notes |
|---|---|---|
| Public source-code repository | **Done** | https://github.com/Rohit-998/Graph-Hack (public, `main`) |
| README with setup, graph data model, Cypher queries/algorithms | **Done** | [README.md](../README.md) - setup, mermaid model, 8 queries copied from code, benchmark |
| Demo video of the working project | **To record** | Script: [demo-script.md](demo-script.md), rehearsed to 2:30 |
| Live deployment **or** complete local setup + verification | **Done (local)** | `docker compose up --build` -> http://localhost:8000; verify steps in README |
| Tracks named (01, 02, 03) with mapping | **Done** | README "Track mapping" |
| AI coding assistant usage disclosed | **Done** | README "AI assistance disclosure" |
| Blog post (side prize) | **Drafted** | [blog.md](blog.md) - needs publishing to a public URL |

## Optional / stretch

| Requirement | Status | Notes |
|---|---|---|
| MCP server with >= 2 tools (Track 01) | **Done** | 6 tools, stdio + streamable HTTP, tested over a real MCP session |
| Historian behavior (similar incidents) | **Done** | Vector recall + structural overlap, confidence boost shown as a bar |
| Scribe memory loop | **Done** | Postmortem, `SIMILAR_TO`, playbook counts, `EXPERT_IN` |
| Playbook reinforcement + learning curve | **Done** | `GET /api/memory/playbooks`, `/api/memory/learning-curve`, `M` panel |
| Incident timeline view | **Not built** | Incident room shows steps, hypotheses, actions; a dedicated timeline is cut |
| Memory library view | **Done** | `M` memory panel |
| Discord/Slack webhook | **Not built** | In-app feed only |
| Benchmark runner + baselines | **Done** | Two worlds, [benchmark.md](benchmark.md) and [benchmark-meridian.md](benchmark-meridian.md): 100% vs 31-38% (most recent change) vs 75-88% (flat LLM) |
| Guarded read-only Cypher tool | **Not built** | Cut for time; Ask Firebreak uses fixed queries |
| Conversation history persistence | **Partial** | localStorage in the Ask panel |
| SSE stream | **Not built** | 2s polling is the documented primary |
| LLM status indicator | **Done** | Header badge: model, call count, errors |
| Real graph algorithms | **Done** | FalkorDB `algo.pageRank` (criticality) and `algo.betweenness` (SPOF panel) |
| Second world | **Done** | Meridian (streaming); acceptance gate and benchmark per world, both in CI; switchable live |
| LLM tool selection | **Done** | Investigator picks MCP tools itself; accepted only if it cites tool output and matches the graph |
| Pre-deploy risk check | **Done** | API, MCP tool, CLI and panel; transparent factor weights |
| Guided demo | **Done** | `D` plays the full story with captions against the real API |

## Gates before submitting

- [x] `uv run pytest` green (34 tests; the integration and MCP tests need FalkorDB and skip without it)
- [x] `uv run python -m firebreak.cli acceptance` green on its own tenant graph (4/4 scenarios)
- [x] CI green on `main` (backend tests + acceptance, frontend lint + build)
- [x] **3 consecutive deterministic runs pass** (PRD §15 reliability gate) - enforced in CI on every push
      (`Acceptance gate x3`), 4/4 scenarios each run
- [ ] Backup demo video recorded
- [ ] Blog published and linked from the README
- [ ] Submission form filled in before 9 PM IST Oct 18 (3h buffer)

## Reproducing the gates

```bash
docker compose up -d falkordb
cd backend
uv run pytest
uv run python -m firebreak.cli acceptance
uv run python -m firebreak.benchmark --n 16
```

CI already runs the acceptance gate three times in a row on every push; run it locally the same way before recording.
