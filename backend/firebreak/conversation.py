"""Persistent conversation memory for Ask Firebreak (Track 02: persistent history, per-user memory).

Conversations are part of the graph, not a side store:

  (:User {id})-[:STARTED]->(:Conversation {id, title, started_at, updated_at})
  (:Conversation)-[:HAS_MESSAGE]->(:Message {seq, role, text, ts})-[:NEXT]->(:Message) ...
  (:Message)-[:CITES {rank}]->(Decision | Runbook | Thread | Incident)
  (:Message)-[:ABOUT {rank}]->(:Component)

Because answers are linked to the entities they cited, a follow-up such as "who decided it?"
is resolved by walking from the previous answer to its sources, not by re-reading prose.
Each tenant graph holds its own users, so memory is separated per tenant and per user.
"""

import re
import time
import uuid

from falkordb import Graph

from . import brain
from . import tools as T
from .db import rows

FOLLOW_UP = re.compile(r"\b(it|its|that|this|they|them|those|he|she|him|her|there)\b", re.I)


def now_ms() -> int:
    return int(time.time() * 1000)


def _ensure_user(g: Graph, user: str) -> None:
    g.query("MERGE (u:User {id: $id}) ON CREATE SET u.created_at = $ts", {"id": user, "ts": now_ms()})


def start(g: Graph, user: str, title: str) -> str:
    _ensure_user(g, user)
    cid = f"CONV-{uuid.uuid4().hex[:8]}"
    g.query("""
        MATCH (u:User {id: $user})
        CREATE (u)-[:STARTED]->(:Conversation {id: $id, title: $title, started_at: $ts, updated_at: $ts})
    """, {"user": user, "id": cid, "title": title[:80], "ts": now_ms()})
    return cid


def _owner(g: Graph, cid: str) -> str | None:
    r = rows(g, "MATCH (u:User)-[:STARTED]->(:Conversation {id: $id}) RETURN u.id AS u", {"id": cid})
    return r[0]["u"] if r else None


def _append(g: Graph, cid: str, role: str, text: str, cites: list[str], about: list[str]) -> str:
    """Append a message. `seq` orders messages (timestamps tie within a millisecond) and `rank`
    on CITES/ABOUT keeps the order sources were cited in, which follow-ups rely on."""
    mid = f"MSG-{uuid.uuid4().hex[:10]}"
    ts = now_ms()
    g.query("""
        MATCH (c:Conversation {id: $cid})
        SET c.seq = coalesce(c.seq, 0) + 1, c.updated_at = $ts
        WITH c
        OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(last:Message {seq: c.seq - 1})
        CREATE (c)-[:HAS_MESSAGE]->(m:Message {id: $mid, role: $role, text: $text, ts: $ts, seq: c.seq})
        FOREACH (_ IN CASE WHEN last IS NULL THEN [] ELSE [1] END | CREATE (last)-[:NEXT]->(m))
    """, {"cid": cid, "mid": mid, "role": role, "text": text, "ts": ts})
    if cites:
        g.query("""
            MATCH (m:Message {id: $mid})
            UNWIND range(0, size($ids) - 1) AS i
            MATCH (s) WHERE (s:Decision OR s:Runbook OR s:Thread OR s:Incident) AND s.id = $ids[i]
            MERGE (m)-[r:CITES]->(s) SET r.rank = i
        """, {"mid": mid, "ids": cites})
    if about:
        g.query("""
            MATCH (m:Message {id: $mid})
            UNWIND range(0, size($names) - 1) AS i
            MATCH (c:Component {name: $names[i]})
            MERGE (m)-[r:ABOUT]->(c) SET r.rank = i
        """, {"mid": mid, "names": about})
    return mid


def _last_answer_context(g: Graph, cid: str) -> dict | None:
    """The sources and components cited by the most recent assistant message, in cited order."""
    last = rows(g, """
        MATCH (:Conversation {id: $cid})-[:HAS_MESSAGE]->(m:Message {role: 'assistant'})
        RETURN m.id AS id ORDER BY m.seq DESC LIMIT 1
    """, {"cid": cid})
    if not last:
        return None
    mid = last[0]["id"]
    sources = rows(g, """
        MATCH (:Message {id: $mid})-[r:CITES]->(s)
        RETURN s.id AS id, labels(s)[0] AS label ORDER BY r.rank
    """, {"mid": mid})
    comps = rows(g, """
        MATCH (:Message {id: $mid})-[r:ABOUT]->(c:Component)
        RETURN c.name AS name ORDER BY r.rank
    """, {"mid": mid})
    return {"id": mid, "sources": sources, "components": [c["name"] for c in comps]}


def _is_follow_up(g: Graph, question: str) -> bool:
    if brain.mentioned_components(g, question):
        return False
    return bool(FOLLOW_UP.search(question)) or len(question.split()) <= 4


def _answer_follow_up(g: Graph, question: str, ctx: dict) -> dict | None:
    """Resolve a follow-up by walking from the previous answer's cited entities."""
    q = question.lower()
    top = ctx["sources"][0] if ctx["sources"] else None
    comps = ctx["components"]

    if top and top["label"] == "Decision" and re.search(r"\bwho\b.*\b(decid|made|chose|agree|approv)", q):
        r = rows(g, """
            MATCH (d:Decision {id: $id})
            OPTIONAL MATCH (p:Person)-[:DECIDED]->(d)
            OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
            OPTIONAL MATCH (d)-[:DISCUSSED_IN]->(th:Thread)
            RETURN d.id AS id, d.title AS title, collect(DISTINCT p.name + ' (' + coalesce(t.name, 'leadership') + ')') AS people,
                   collect(DISTINCT th.id) AS threads
        """, {"id": top["id"]})[0]
        return {"answer": f"{r['id']} \"{r['title']}\" was decided by {', '.join(r['people'])}"
                          + (f", discussed in {', '.join(r['threads'])}." if r["threads"] else "."),
                "sources": [{"type": "Decision", "id": r["id"], "title": r["title"], "people": [], "components": comps}]
                + [{"type": "Thread", "id": t, "title": "", "people": [], "components": []} for t in r["threads"]],
                "highlight": comps}

    if comps and re.search(r"\b(broke|break|incident|outage|fail|went wrong|before)\b", q):
        r = rows(g, """
            MATCH (i:Incident)-[:AFFECTED]->(c:Component) WHERE c.name IN $comps AND i.status = 'resolved'
            OPTIONAL MATCH (i)-[:ROOT_CAUSE]->(rc)
            RETURN DISTINCT i.id AS id, i.title AS title, coalesce(rc.id, rc.name) AS cause, i.started_at AS ts
            ORDER BY ts DESC LIMIT 4
        """, {"comps": comps})
        if r:
            return {"answer": "Past incidents touching " + ", ".join(comps[:3]) + ": "
                              + "; ".join(f"{x['id']} {x['title']} (cause {x['cause']})" for x in r) + ".",
                    "sources": [{"type": "Incident", "id": x["id"], "title": x["title"], "people": [],
                                 "components": comps} for x in r],
                    "highlight": comps}

    if comps and re.search(r"\bwho\b.*\b(know|fix|expert|own|ask|call|page|help)", q):
        target = comps[0]
        oc = T.owners_and_oncall(g, target, now_ms()).data
        ex = T.who_knows(g, target).data
        team = oc[0]["team"] if oc else "?"
        return {"answer": f"{target} is owned by {team}; on call now: "
                          + ", ".join(f"{o['on_call']} (L{o['level']})" for o in oc if o["on_call"])
                          + ". People who know it best: "
                          + ", ".join(f"{e['name']} ({e['reasons'][0]})" for e in ex) + ".",
                "sources": [], "highlight": [target]}
    return None


def ask(g: Graph, user: str, question: str, conversation: str | None = None) -> dict:
    if conversation and _owner(g, conversation) not in (None, user):
        raise PermissionError("conversation belongs to another user")
    cid = conversation if conversation and _owner(g, conversation) == user else start(g, user, question)

    ctx = _last_answer_context(g, cid)
    resolved = None
    if ctx and _is_follow_up(g, question):
        resolved = _answer_follow_up(g, question, ctx)
        if resolved is None and (ctx["components"] or ctx["sources"]):
            # Generic follow-up: re-ask with the previous answer's subject folded in.
            subject = " ".join(ctx["components"][:2] + [s["id"] for s in ctx["sources"][:1]])
            resolved = brain.answer(g, f"{question} {subject}")

    a = resolved or brain.answer(g, question)
    a.setdefault("model", "deterministic")
    a["question"] = question
    a["conversation"] = cid
    a["follow_up_of"] = ctx["id"] if (resolved and ctx) else None

    _append(g, cid, "user", question, [], brain.mentioned_components(g, question))
    _append(g, cid, "assistant", a["answer"], [s["id"] for s in a.get("sources", []) if s.get("id")],
            a.get("highlight", []))
    return a


def history(g: Graph, user: str, conversation: str) -> list[dict]:
    if _owner(g, conversation) != user:
        raise PermissionError("conversation belongs to another user")
    msgs = rows(g, """
        MATCH (:Conversation {id: $cid})-[:HAS_MESSAGE]->(m:Message)
        RETURN m.id AS id, m.role AS role, m.text AS text, m.ts AS ts, m.seq AS seq
        ORDER BY m.seq
    """, {"cid": conversation})
    for m in msgs:
        m["cites"] = [r["id"] for r in rows(g, """
            MATCH (:Message {id: $mid})-[r:CITES]->(s) RETURN s.id AS id ORDER BY r.rank
        """, {"mid": m["id"]})]
    return msgs


def conversations(g: Graph, user: str) -> list[dict]:
    return rows(g, """
        MATCH (:User {id: $user})-[:STARTED]->(c:Conversation)
        OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
        RETURN c.id AS id, c.title AS title, c.updated_at AS updated_at, count(m) AS messages
        ORDER BY updated_at DESC LIMIT 20
    """, {"user": user})
