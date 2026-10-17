# The alert is on checkout. The cause is not.

*How we built Firebreak, an incident commander whose context lives in a FalkorDB graph, for Graph Hacks.*

At 3 AM checkout starts failing. The pager says `checkout-api`. Ten minutes later you find out the real
problem was a deploy to `auth-service`, two hops away, a service that never alerted. Meanwhile someone
spent those ten minutes on a search deploy that went out four minutes before the outage, because it was
the most recent thing that changed.

That gap between symptom and cause is a graph problem, and it's why we built **Firebreak**.

## Agents see pieces

Give an LLM the alerts and the list of recent changes and ask for the root cause. It will often get it
right. In our benchmark a flat-context Gemini model got 75% of generated scenarios right on one
company and 88% on another, which beats the "blame the latest deploy" heuristic (31% and 38%). But look at what it misses: vendor outages
and causes several hops from the alert. Nothing in a flat list says that `checkout-api` calls
`payments-core`, which calls `stripe`. The model has to guess the topology, and sometimes it guesses wrong.

Firebreak gets 100% on the same scenarios, on both companies, with zero LLM calls. Not because it is
clever, but because the question it asks is one a graph answers directly: *which recent change sits
under every alerting service?*

## One graph for everything

NimbusPay, our fictional fintech, lives in one FalkorDB graph: 35 components with `DEPENDS_ON` edges
(each marked `sync` or `async`), teams, people, on-call rotations, products, customers with GMV per hour,
90 days of changes, 15 past incidents, ADRs, runbooks and Slack threads.

The rule we set from the start, straight from the hackathon brief: if the product works without
FalkorDB, the graph is decoration. So the simulator reads the topology from the graph and writes health
and alerts back. Every agent tool is a Cypher query. The agents coordinate through nodes in the graph.
Memory is in the graph. Pull FalkorDB out and nothing runs.

## The query that does the work

The Detective starts from the alerting services and walks down dependencies:

```cypher
UNWIND $alerting AS a
MATCH (s:Component {name: a})
MATCH p = (s)-[:DEPENDS_ON*0..6]->(c:Component)
WITH c, a, min(length(p)) AS hops
WITH c, collect({alert: a, hops: hops}) AS explains
OPTIONAL MATCH (c)-[:DEPENDS_ON {mode: 'sync'}]->(d:Component) WHERE d.status <> 'healthy'
RETURN c.name AS candidate, c.status AS status, explains, count(d) = 0 AS origin
```

That gives every candidate its **coverage** (how many alerts it could explain) and whether it is an
**origin** (degraded, with no degraded dependency beneath it) or just another symptom. Then:

```
score(c) = coverage × (0.45·recent change + 0.25·anomaly + 0.20·history + 0.30·vendor) + 0.05·criticality
```

Coverage multiplies everything. The decoy search deploy explains zero of three alerts, so its
recency is worth exactly nothing. That one multiplication is the whole difference between Firebreak
and the latest-deploy heuristic.

Criticality isn't a count we made up: it's FalkorDB's own PageRank over `DEPENDS_ON`, run inside the
database (`CALL algo.pageRank('Component', 'DEPENDS_ON')`), so rank flows through dependency chains and a
deep shared datastore outranks a leaf with many callers. Betweenness centrality from the same algorithm
library drives a single-points-of-failure view: on NimbusPay, `checkout-api`, `payments-core` and
`auth-service` are where one failure severs the most unrelated paths.

## Is it just tuned to the demo?

That's the first question we'd ask, so we built a second company. Meridian is a streaming platform with
a different shape: a fan-out of TV, mobile and web clients onto playback, DRM and a CDN, then
recommendation and data pipelines. Same engine, no special cases, its own FalkorDB graph. The benchmark
generates 16 scenarios from each topology, with a decoy in every one:

| | NimbusPay | Meridian |
|---|---|---|
| Firebreak (graph, 0 LLM calls) | 100% | 100% |
| Flat-context LLM | 75% | 88% |
| Most recent change | 31% | 38% |

Building Meridian also caught a real bug. Services that were only failing because of something
downstream were being counted as independent evidence, which diluted the verdict whenever the blast
radius was wide. We fixed the engine, not the weights.

## Three agents, one blackboard

The Commander opens the incident and dispatches the Detective and the Responder in parallel. They don't
pass findings to each other. The Detective writes `Hypothesis` nodes, including the rejected decoys and
why they were rejected. The Responder writes who owns the suspect, who is on call, and who actually knows
the system, ranked by who responded to past incidents on it, wrote its runbook, or changed it. Both log
every step as an `AgentStep` node with the exact Cypher it ran.

Then the Commander reads the blackboard back out of FalkorDB and decides. It writes
`(:Incident)-[:ROOT_CAUSE]->(:Change)`, an evidence path (`checkout-api → auth-service`), blast radius,
customers and dollars at risk, and proposes a rollback for a human to approve. Click approve and the map
goes green.

## Memory that pays off

Every incident is embedded locally (bge-small, 384 dimensions, no API quota) into a FalkorDB vector
index. Before deciding, the Commander recalls similar past incidents, combining vector similarity with
overlap of the affected components. When a past incident had the same root cause, the verdict says so:

> **Seen before:** INC-2093 "Checkout and payouts rejecting valid tokens" · rollback resolved it in 6 min

After the fix, the Scribe writes a postmortem into the graph, links `SIMILAR_TO` incidents, bumps the
playbook's success count and raises the responders' `EXPERT_IN` score. Next time the proposed rollback
says "playbook: 3/3 past successes", and the right people float to the top of the page list.

## Free-tier LLMs, used carefully

We're students, so free-tier Gemini only, and free-tier quotas run out. So the graph makes every
decision, and the LLM only writes prose: the verdict narrative and the postmortem. Its narrative is
thrown away unless it cites the graph-chosen root cause, and every failure falls back to a template. The UI
labels every step `deterministic` or with the model that wrote it. The demo cannot die to a 429.

There is one place the LLM gets more room. Every graph tool is also an MCP server, and the verdict card
offers a **second opinion**: an LLM is handed the tool list, no answers, and picks which tools to call
itself. Its verdict is accepted only if it cites something a tool actually returned *and* matches the
graph's answer; otherwise it is stored as a rejected hypothesis. In one test it was pointed at an
incident that had already been fixed, so the tools found no candidates; it guessed `checkout-api` anyway,
and the check threw it out. The LLM may choose how to look, never what is true.

## Ask the company brain

The same graph answers "why" questions. *Why does checkout call auth synchronously?* Full-text search
finds ADR-014, and the graph adds who decided it (Aisha Bello, Hana Kim), where it was argued (a Slack
thread), and which services it touches, highlighted on the map. The answer cites its sources because
the sources are nodes.

Conversations are nodes too. Each answer is stored as a `Message` with ranked `CITES` edges to what it
used, per user. So when you follow up with *"Who decided it?"*, Firebreak doesn't re-read its own prose
to guess what "it" means: it walks from the previous answer's cited Decision to the `DECIDED` edges.
Each user sees only their own conversations, inside their own tenant graph.

A company brain also goes stale, so new docs, tickets and chats can be added live. Each one is linked to
the components, people and records it names, the links are shown so you can check them, and it is
searchable straight away. Knowledge its subject has outgrown is flagged with the reason: a runbook gets
flagged when incidents hit what it covers after its last review, and a decision gets flagged when newer
tickets reference it.

## Looking forward, not just back

Incident response is the graph looking backwards. The same graph also answers forwards: click any
service and ask what happens if you ship a change to it. A deploy to `auth-service` comes back **high
risk**: a deploy there caused INC-2093 and was rolled back in 6 minutes, ADR-014 makes it a hard
dependency of every payment path, and Priya Raman should review it. A deploy to `email-worker` comes back
**low**. Every factor in the score is listed with its weight. The more incidents the Scribe writes up,
the sharper this gets: memory from the last outage is what prevents the next one.

## Many tenants, one instance

FalkorDB holds one graph per tenant, so memory never mixes. We measured it: a load test seeds 12 tenant
graphs from both companies in one FalkorDB instance and runs them all at once, with an incident
investigation in each, four users per tenant holding conversations, pre-deploy checks and algorithm calls.
192 operations in about a second, 144 of them graph writes, 12 out of 12 correct verdicts, 12 out of 12
decoys rejected, and zero nodes visible across tenants. It runs in CI on every push.

## What we'd do next

Real integrations: OpenTelemetry service graphs instead of a seeded topology, deploy events from CI
feeding the pre-deploy check automatically, PagerDuty for paging, and Slack ingestion into the
knowledge graph. And agent-proposed `DEPENDS_ON` edges learned from traces, reviewed by a human before
they count.

Firebreak is open source: <https://github.com/Rohit-998/Graph-Hack>. `docker compose up --build` and
open `localhost:8000`.

*Built with the help of an AI coding assistant.*
