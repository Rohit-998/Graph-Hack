# Demo video script (target 2:50, hard cap 3:00)

Record on the live site: **https://graph-hack.onrender.com** at 1440×900 or larger, browser zoom 100%.

## Before you hit record (5 minutes)

1. Open the site in a **fresh incognito window** about 2 minutes early. The free server may need about a
   minute to wake up ("Waking up the graph…"). A fresh window also gives you a fresh private copy of the
   graph, so nothing from earlier testing shows.
2. Check the header shows **NimbusPay · fintech** and the map is all green.
3. Close every panel except the **Chaos lab** (top left). Leave the right panel on "Mission control".
4. Hide your bookmarks bar and notifications. Record the browser tab only.
5. Do not rehearse an injection in this window: the first inject should be the one on camera.

Easiest fallback: press **D** (or **Run demo**, top right). It plays the main story with captions in
about 75 seconds against the real API; you can narrate over it and record the extra beats after it.

## The script

| Time | On screen / what you do | What you say |
|---|---|---|
| **0:00 – 0:12** | Map all green. Cursor still. | "At 3 AM, checkout is failing. The alert is on checkout. But the cause isn't. It's two services away, in something that never alerted." |
| **0:12 – 0:25** | Point at the bottom strip (35 components, 19 people, 5 customers, incidents), then sweep across the map. | "This is Firebreak. Every service, dependency, deploy, person, on-call rotation, customer and past incident of this company lives in one FalkorDB graph. Gold lines are synchronous calls, teal dashes are async." |
| **0:25 – 0:35** | In Chaos lab, keep **with decoy** ticked and click **1 · Bad deploy on auth-service**. | "Let's break it. A bad deploy goes out to auth-service, and a few minutes later, an unrelated deploy goes out to search. That second one is a decoy." |
| **0:35 – 0:50** | Watch the red glow spread. Point at the three **ALERT** tags (checkout-api, web-bff, payouts-api), then at auth-service with no tag. Point at the KPI strip: SEV1, $108,000/h at risk, SLA clock. | "Errors flow up the synchronous edges. Checkout, web and payouts alert. Auth-service, the actual cause, doesn't. The graph already knows which customers are exposed: four of them, a hundred and eight thousand dollars an hour, and the SLA clock is running." |
| **0:50 – 1:08** | Right panel, scroll the **Agent room** down to the hypothesis board. Point at the **REJECTED** row "deploy D-4522 on search-service explains 0/3 alerts". | "Three agents work the incident. The Detective and the Responder run in parallel, and they don't pass prompts to each other. They write Hypothesis nodes into the graph, and the Commander reads them back. Here's the decoy: the most recent deploy, rejected, because it explains zero of three alerts. Nothing that's alerting depends on search." |
| **1:08 – 1:25** | Scroll up to the verdict: "Root cause: deploy D-4521 to auth-service by Priya Raman, 95%". Point at the breakdown bars. Click **Show evidence path** (or press **E**); the gold path draws and the root cause lights up. | "The verdict: deploy D-4521 to auth-service, by Priya Raman, ninety-five percent. Every bar is a graph signal: alert coverage, change timing, anomaly, history, and PageRank computed inside FalkorDB. And here's the evidence path, hop by hop: checkout-api, to auth-service." |
| **1:25 – 1:33** | Point at the green **Seen before** banner. | "It's also seen this before. INC-2093: same component, same kind of change. A rollback fixed it in six minutes." |
| **1:33 – 1:48** | Click **Approve** on the **ROLLBACK** action. Map turns green; KPI strip returns to "All systems operational". Scroll down to "Scribe · postmortem written to graph". | "A human approves. The map goes green. And the Scribe writes the postmortem back into the graph, updates the playbook's success count, and raises the responders' expertise, so the next incident is faster." |
| **1:48 – 2:08** | Click the bottom **Ask** bar, type `Why does checkout call auth synchronously?` and press Enter. When it answers, click the **Who decided it?** chip. Point at "follow-up · resolved from graph". | "The same graph is the company brain. Why does checkout call auth synchronously? ADR-014, with the Slack thread it was argued in, highlighted on the map. And it remembers the conversation: 'who decided it' is answered by walking from the cited decision to the people who made it. Aisha Bello and Hana Kim." |
| **2:08 – 2:24** | Press **Esc**. Click the **auth-service** orb, then **Check a change here before shipping**. Point at **HIGH RISK**, the first advice line (it cites the incident you just fixed, e.g. INC-2186), and "What broke here before" (INC-2093 is in the list). | "It also looks forward. Before the next deploy to auth-service, the graph says: high risk. It already knows about the incident we fixed a minute ago, and INC-2093 before that. Read ADR-014 first, and get Priya to review it. Memory from the last outage is what prevents the next one." |
| **2:24 – 2:40** | Close the panel. In the header, switch the company to **Meridian · streaming** (map reshapes). Press **2** (vendor outage). Point at the verdict "cdn is degraded" and the **FAILOVER** action. | "And it isn't tuned to one demo. This is a different company, a streaming platform with a different shape, in its own FalkorDB graph. Same engine, no changes: it finds the CDN, rejects the decoy, and proposes a failover." |
| **2:40 – 2:52** | Optional: press **Ctrl K**, switch to **Query the graph**, click the GMV example; the Cypher and a results table appear. | "Across sixteen generated scenarios per company, it gets the root cause every time with zero LLM calls. Blaming the latest deploy gets a third. And everything is open: every tool is an MCP server, and you can query the graph directly, read-only, enforced by FalkorDB." |
| **2:52 – 3:00** | Back to the map. | "Firebreak. Stop incidents from spreading." |

## Lines to cut if you run long

Drop in this order: the Query beat (2:40), the Meridian beat (2:24), then the pre-deploy beat (2:08).
Never cut inject → spread → decoy rejected → verdict. That is Track 01.

## If something goes wrong on camera

- **Map doesn't load:** wait; the server is waking up. Cut that part out in editing.
- **Second injection shows "D-4521-2":** your window isn't fresh. Open a new incognito window.
- **Ask answer looks different:** say the line anyway; ADR-014 is always the first source.
- **Anything else:** press **D**, let the guided demo play, and narrate over it.

## Upload checklist

- 1080p, under 3:00, title: "Firebreak: an AI incident commander on a FalkorDB knowledge graph".
- Description: the live link, the repo link, and "Tracks 01, 02 and 03".
- Put the video link in the README and the submission form.
