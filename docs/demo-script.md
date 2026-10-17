# Demo video script (target 2:30, hard cap 3:00)

Setup before recording: `docker compose up --build`, open http://localhost:8000 at 1440×900 or larger.

**Easiest take:** press `D` (or **Run demo**). It plays the beats below with on-screen captions against the
real API in about 75 seconds; narrate over it, then do the extra beats at the end by hand.

Manual take: click **Reset world**, and do one throwaway bad-deploy run first so "seen before" has fresh memory.

| Time | Do | Say |
|---|---|---|
| 0:00 | Map all green | "At 3 AM checkout is failing. The alert is on checkout. The cause is not." |
| 0:10 | Hover the header stats | "This is NimbusPay: 35 services, 19 people, 5 customers, every past incident. One FalkorDB graph." |
| 0:20 | Press `1` (bad deploy, decoy on) | "A bad deploy hits auth-service. Four minutes later, an unrelated search deploy goes out." |
| 0:30 | Point at red edges and ALERT tags | "Errors flow up sync edges. Checkout, web and payouts alert. auth-service doesn't." |
| 0:45 | Agent room | "Detective and Responder run in parallel and write to the graph, not to each other. The decoy is rejected: it explains zero of three alerts." |
| 1:05 | Verdict card | "Deploy D-4521 by Priya Raman, 95%. Here's why:" press `E` "the evidence path, hop by hop." |
| 1:20 | Seen-before banner | "And it's seen this before: INC-2093, rollback fixed it in 6 minutes." |
| 1:30 | Click **Approve** on rollback | "A human approves. Map goes green. The Scribe writes the postmortem into the graph." |
| 1:45 | Press `M` | "Memory: the rollback playbook now has another success, and the people who fixed it are now ranked as experts on it." |
| 2:00 | `Ctrl+K`, ask "Why does checkout call auth synchronously?" | "The same graph is the company brain: ADR-014, who decided it, the Slack thread, highlighted on the map." |
| 2:15 | Show docs/benchmark.md | "Two different companies, 16 generated scenarios each: 100% with zero LLM calls. Most-recent-deploy gets 31 to 38%. A flat-context LLM gets 75 to 88%." |
| 2:20 | Click `auth-service`, **Check a change here before shipping** | "And before the next deploy: the graph says high risk, cites INC-2093 and ADR-014, and names the reviewer." |
| 2:30 | Header: switch to **Meridian**, press `2` | "Different company, same engine: it finds the CDN, rejects the decoy, proposes failover." |
| 2:45 | Map | "Firebreak. Stop incidents from spreading." |

Fallback if live demo flakes: record each beat separately and cut. The CLI path works without the UI:
`uv run python -m firebreak.cli acceptance`.
