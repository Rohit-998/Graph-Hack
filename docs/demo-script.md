# Demo video script (target 2:30, hard cap 3:00)

Setup before recording: `docker compose up --build`, open http://localhost:8000 at 1440×900 or larger,
click **Reset world**. Do one throwaway bad-deploy run first so the "seen before" beat has fresh memory.

| Time | Do | Say |
|---|---|---|
| 0:00 | Map all green | "At 3 AM checkout is failing. The alert is on checkout. The cause is not." |
| 0:10 | Hover the header stats | "This is NimbusPay: 35 services, 19 people, 5 customers, every past incident. One FalkorDB graph." |
| 0:20 | Press `1` (bad deploy, decoy on) | "A bad deploy hits auth-service. Four minutes later, an unrelated search deploy goes out." |
| 0:30 | Point at red edges and ALERT tags | "Errors flow up sync edges. Checkout, web and payouts alert. auth-service doesn't." |
| 0:45 | Agent room | "Detective and Responder run in parallel and write to the graph, not to each other. The decoy is rejected: it explains zero of three alerts." |
| 1:05 | Verdict card | "Deploy D-4521 by Priya Raman, 94%. Here's why:" press `E` "the evidence path, hop by hop." |
| 1:20 | Seen-before banner | "And it's seen this before: INC-2093, rollback fixed it in 6 minutes." |
| 1:30 | Click **Approve** on rollback | "A human approves. Map goes green. The Scribe writes the postmortem into the graph." |
| 1:45 | Press `M` | "Memory: the rollback playbook now has another success, and the people who fixed it are now ranked as experts on it." |
| 2:00 | `Ctrl+K`, ask "Why does checkout call auth synchronously?" | "The same graph is the company brain: ADR-014, who decided it, the Slack thread, highlighted on the map." |
| 2:15 | Show docs/benchmark.md | "On 16 generated scenarios: 100% with zero LLM calls. Most-recent-deploy gets 31%. A flat-context LLM gets 75%." |
| 2:25 | Show MCP config in README | "Every tool is also an MCP server, so any agent can use the graph." |
| 2:35 | Map | "Firebreak. Stop incidents from spreading." |

Fallback if live demo flakes: record each beat separately and cut. The CLI path works without the UI:
`uv run python -m firebreak.cli acceptance`.
