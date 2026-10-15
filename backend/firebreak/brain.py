"""Ask Firebreak: company-brain Q&A with cited sources (PRD FR-7.1).

Deterministic pipeline: full-text search over decisions, runbooks, threads and
incidents -> expand the top hit's neighborhood in the graph -> extractive answer
that cites every entity it used.
"""

import re

from falkordb import Graph

from . import tools as T
from .db import rows

STOPWORDS = set("""
a an the is are was were be been do does did why what who whom which how when where to of in on for and or
but with by from at as it this that these those we our us you your i me my can could should would will
there their they them has have had not no yes about into than then so if any all ever
""".split())

COMPONENT_NAMES = "MATCH (c:Component) RETURN c.name AS name"

NEIGHBORHOOD = """
MATCH (c:Component {name: $name})
OPTIONAL MATCH (t:Team)-[:OWNS]->(c)
OPTIONAL MATCH (c)-[:DEPENDS_ON]->(d:Component)
OPTIONAL MATCH (u:Component)-[:DEPENDS_ON]->(c)
RETURN c.name AS name, c.description AS description, t.name AS team,
       collect(DISTINCT d.name) AS depends_on, collect(DISTINCT u.name) AS used_by
"""


def to_query(question: str) -> str:
    words = re.findall(r"[a-z0-9]+", question.lower())
    terms = [w for w in words if w not in STOPWORDS and len(w) > 2]
    # Prefix match so "synchronously" also finds "synchronous".
    return "|".join(f"{t[:-2]}*" if len(t) > 6 else t for t in dict.fromkeys(terms)) or question


def mentioned_components(g: Graph, question: str) -> list[str]:
    q = question.lower()
    names = [r["name"] for r in rows(g, COMPONENT_NAMES)]
    hits = [n for n in names if n in q]
    # Allow "checkout" for checkout-api, "auth" for auth-service.
    for n in names:
        head = n.split("-")[0]
        if n not in hits and len(head) > 3 and re.search(rf"\b{re.escape(head)}\b", q):
            hits.append(n)
    return hits


def answer(g: Graph, question: str) -> dict:
    q = to_query(question)
    search = T.search_knowledge(g, q)
    hits = search.data
    comps = mentioned_components(g, question)
    # "Why" / "who decided" questions are about decisions: prefer the ADR and cite its threads.
    # "Why" / "who decided" questions want the ADR; "how do I" questions want the runbook.
    ql = question.lower()
    preferred = ("Decision" if re.search(r"\b(why|decid\w*|decision|reason)\b", ql)
                 else "Runbook" if re.search(r"\bhow (do|to|can|should)\b", ql) else None)
    # Rank hits that touch the components the user named above generic matches.
    hits.sort(key=lambda h: (
        -len(set(h["components"]) & set(comps)),
        -(h["type"] == preferred),
        -h["score"],
    ))
    hits = hits[:5]

    neighborhoods = [r for c in comps[:3] for r in rows(g, NEIGHBORHOOD, {"name": c})]

    if not hits and not neighborhoods:
        return {"question": question, "query": q, "answer": "I couldn't find anything in the graph about that.",
                "sources": [], "highlight": [], "model": "deterministic"}

    parts = []
    if hits:
        top = hits[0]
        lead = {"Decision": "Per", "Runbook": "Runbook", "Thread": "From thread", "Incident": "In"}[top["type"]]
        parts.append(f"{lead} {top['id']} \"{top['title']}\": {top['text']}")
        if top["people"]:
            verb = "Decided by" if top["type"] == "Decision" else "Involving"
            parts.append(f"{verb} {', '.join(top['people'])}.")
        if top["threads"]:
            parts.append(f"Discussed in {', '.join(top['threads'])}.")
    for n in neighborhoods:
        if not hits or n["name"] not in hits[0]["components"]:
            parts.append(f"{n['name']} is owned by {n['team']} and depends on {', '.join(n['depends_on']) or 'nothing'}.")

    highlight = list(dict.fromkeys(
        [c for h in hits[:2] for c in h["components"]] + [n["name"] for n in neighborhoods]
    ))
    sources = [{"type": h["type"], "id": h["id"], "title": h["title"], "people": h["people"],
                "components": h["components"], "score": round(h["score"], 3)} for h in hits]
    return {"question": question, "query": q, "answer": " ".join(parts), "sources": sources,
            "highlight": highlight, "cypher": search.cypher, "model": "deterministic"}
