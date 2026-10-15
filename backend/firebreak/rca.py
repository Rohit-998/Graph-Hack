"""Root-cause scoring (PRD §9.3). Pure functions: graph facts in, ranked candidates out.

score(c) = coverage(c) * (0.45*change + 0.25*anomaly + 0.20*history + 0.30*vendor)
           + 0.05*criticality(c)

A candidate that explains none of the alerts (coverage = 0) can only score the
small criticality term, so a recent decoy change off the dependency path loses.

Anomaly is full weight only for an *origin*: a degraded component whose sync
dependencies are all healthy. A degraded component downstream of another
degraded one is a symptom and gets a fraction.

Confidence is normalized across candidates with direct evidence (a change,
an anomaly or a vendor signal). Healthy, unchanged components get 0%.
"""

import math
from dataclasses import dataclass, field

W_CHANGE, W_ANOMALY, W_HISTORY, W_VENDOR, W_CRIT = 0.45, 0.25, 0.20, 0.30, 0.05
CHANGE_HALF_LIFE_MIN = 30
RISK_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}
SYMPTOM_ANOMALY = 0.2


@dataclass
class ChangeFact:
    id: str
    component: str
    kind: str
    summary: str
    risk: str
    ts: int
    author: str | None = None


@dataclass
class CandidateFacts:
    component: str
    explains: list[dict]                 # [{"alert": name, "hops": n}]
    kind: str = "service"
    degraded: bool = False               # own health is off-baseline
    origin: bool = True                  # no degraded sync dependency explains it
    criticality: float = 0.0             # normalized 0..1
    history_prior: float = 0.0           # share of similar past incidents rooted here
    changes: list[ChangeFact] = field(default_factory=list)


@dataclass
class Ranked:
    component: str
    score: float
    confidence: float
    coverage: float
    breakdown: dict
    top_change: ChangeFact | None
    explains: list[dict]
    has_evidence: bool = False


def change_signal(changes: list[ChangeFact], now_ms: int) -> tuple[float, ChangeFact | None]:
    best, best_change = 0.0, None
    for ch in changes:
        age_min = max(0.0, (now_ms - ch.ts) / 60_000)
        s = math.exp(-age_min / CHANGE_HALF_LIFE_MIN) * RISK_WEIGHT.get(ch.risk, 0.5)
        if s > best:
            best, best_change = s, ch
    return best, best_change


def rank(candidates: list[CandidateFacts], alert_count: int, now_ms: int) -> list[Ranked]:
    if alert_count <= 0:
        return []
    scored = []
    for c in candidates:
        coverage = len({e["alert"] for e in c.explains}) / alert_count
        chg, top = change_signal(c.changes, now_ms)
        anomaly = (1.0 if c.origin else SYMPTOM_ANOMALY) if c.degraded else 0.0
        vendor = 1.0 if (c.kind == "vendor" and c.degraded and c.origin) else 0.0
        inner = W_CHANGE * chg + W_ANOMALY * anomaly + W_HISTORY * c.history_prior + W_VENDOR * vendor
        score = coverage * inner + W_CRIT * c.criticality
        breakdown = {
            "coverage": round(coverage, 3),
            "change": round(coverage * W_CHANGE * chg, 4),
            "anomaly": round(coverage * W_ANOMALY * anomaly, 4),
            "history": round(coverage * W_HISTORY * c.history_prior, 4),
            "vendor": round(coverage * W_VENDOR * vendor, 4),
            "criticality": round(W_CRIT * c.criticality, 4),
        }
        has_evidence = chg > 0.01 or anomaly > 0 or vendor > 0
        scored.append(Ranked(c.component, score, 0.0, coverage, breakdown, top, c.explains, has_evidence))

    total = sum(r.score for r in scored if r.has_evidence) or 1.0
    for r in scored:
        r.confidence = r.score / total if r.has_evidence else 0.0
    # Ties broken by fewer hops from the alerts (closer to the cause of symptoms), then name.
    scored.sort(key=lambda r: (-r.score, min((e["hops"] for e in r.explains), default=99), r.component))
    return scored
