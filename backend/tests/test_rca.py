from firebreak.rca import CandidateFacts, ChangeFact, rank

NOW = 10_000_000_000
MIN = 60_000

ALERTS = ["checkout-api", "web-bff", "payouts-api"]


def facts():
    # auth-service sits under all three alerting services; the decoy sits under none.
    return [
        CandidateFacts("auth-service", [{"alert": a, "hops": h} for a, h in
                                        [("checkout-api", 1), ("web-bff", 2), ("payouts-api", 1)]],
                       degraded=True, criticality=0.6,
                       changes=[ChangeFact("D-4521", "auth-service", "deploy", "bad", "high", NOW - 8 * MIN, "priya")]),
        CandidateFacts("checkout-api", [{"alert": "checkout-api", "hops": 0}, {"alert": "web-bff", "hops": 1}],
                       degraded=True, origin=False, criticality=0.5),
        CandidateFacts("web-bff", [{"alert": "web-bff", "hops": 0}], degraded=True, origin=False, criticality=0.2),
        # healthy shared dependency under every alert: full coverage, no evidence
        CandidateFacts("postgres-main", [{"alert": a, "hops": 2} for a in ALERTS], criticality=1.0),
        CandidateFacts("search-service", [], criticality=0.3,
                       changes=[ChangeFact("D-4522", "search-service", "deploy", "decoy", "high", NOW - 4 * MIN)]),
    ]


def test_real_cause_beats_decoy_and_symptoms():
    ranked = rank(facts(), len(ALERTS), NOW)
    assert ranked[0].component == "auth-service"
    assert ranked[0].top_change.id == "D-4521"
    assert ranked[0].coverage == 1.0
    decoy = next(r for r in ranked if r.component == "search-service")
    assert decoy.coverage == 0
    assert decoy.breakdown["change"] == 0


def test_confident_verdict_and_no_credit_without_evidence():
    ranked = rank(facts(), len(ALERTS), NOW)
    assert ranked[0].confidence > 0.8
    pg = next(r for r in ranked if r.component == "postgres-main")
    assert pg.confidence == 0.0


def test_confidences_sum_to_one():
    ranked = rank(facts(), len(ALERTS), NOW)
    assert abs(sum(r.confidence for r in ranked) - 1.0) < 1e-9
    assert all(r.confidence == 0 for r in ranked if not r.has_evidence)


def test_degraded_vendor_wins_without_changes():
    cands = [
        CandidateFacts("stripe", [{"alert": "checkout-api", "hops": 2}], kind="vendor", degraded=True),
        CandidateFacts("payments-core", [{"alert": "checkout-api", "hops": 1}], degraded=True, origin=False),
    ]
    assert rank(cands, 1, NOW)[0].component == "stripe"


def test_no_alerts_returns_empty():
    assert rank(facts(), 0, NOW) == []
