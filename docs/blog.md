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

Firebreak gets 100% on the same 16 scenarios with zero LLM calls. Not because it is clever, but because
the question it asks is one a graph answers directly: *which recent change sits under every alerting
service?*

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

## Ask the company brain

The same graph answers "why" questions. *Why does checkout call auth synchronously?* Full-text search
finds ADR-014, and the graph adds who decided it (Aisha Bello, Hana Kim), where it was argued (a Slack
thread), and which services it touches, highlighted on the map. The answer cites its sources because
the sources are nodes.

## What we'd do next

Real integrations: OpenTelemetry service graphs instead of a seeded topology, deploy events from CI,
PagerDuty for paging. And pre-deploy risk: before a change ships, ask the graph what its blast radius is
and what broke the last time someone touched that component.

Firebreak is open source: <https://github.com/Rohit-998/Graph-Hack>. `docker compose up --build` and
open `localhost:8000`.

*Built with the help of an AI coding assistant.*
