# RCA benchmark

16 scenarios generated from the NimbusPay topology (`firebreak/benchmark.py`, seed 7). Each has one real cause and one decoy change on a component no alerting service depends on. In 11 of them the decoy is more recent than the real cause (or the cause is a vendor outage with no change at all).

| Method | Top-1 accuracy | LLM calls / incident |
|---|---|---|
| **Firebreak** (graph RCA, deterministic) | **100%** | 0 |
| Most recent change | 31% | 0 |
| Flat-context LLM (gemini-3.5-flash-lite, no topology) | 75% | 1 |

The flat-LLM baseline is scored leniently: naming the right component counts as correct even without the change id. It sees the same alerts and changes Firebreak does, but not the dependency graph.

Median Firebreak time to verdict: 0.164s (full agent loop, incl. graph writes).

| Scenario | Real cause | Decoy | Firebreak | Most recent | Flat LLM |
|---|---|---|---|---|---|
| catalog-service (flag) | `B-5000` | `B-6000` | ✓ 93% | ✗ `B-6000` | ✗ `sanctions-screening` |
| risk-scoring (flag) | `B-5001` | `B-6001` | ✓ 88% | ✗ `B-6001` | ✓ `risk-scoring` |
| postgres-main (config) | `B-5002` | `B-6002` | ✓ 63% | ✗ `B-6002` | ✓ `B-5002` |
| kyc-service (flag) | `B-5003` | `B-6003` | ✓ 93% | ✗ `B-6003` | ✓ `kyc-service` |
| payments-core (flag) | `B-5004` | `B-6004` | ✓ 87% | ✗ `B-6004` | ✓ `payments-core` |
| user-service (flag) | `B-5005` | `B-6005` | ✓ 79% | ✓ `B-5005` | ✓ `user-service` |
| stripe (vendor outage) | `stripe` | `B-6006` | ✓ 87% | ✗ `B-6006` | ✗ `email-worker` |
| redis-cache (migration) | `B-5007` | `B-6007` | ✓ 78% | ✗ `B-6007` | ✓ `B-5007` |
| onfido (vendor outage) | `onfido` | `B-6008` | ✓ 90% | ✗ `B-6008` | ✗ `checkout-api` |
| fraud-service (flag) | `B-5009` | `B-6009` | ✓ 87% | ✗ `B-6009` | ✓ `fraud-service` |
| search-service (deploy) | `B-5010` | `B-6010` | ✓ 91% | ✓ `B-5010` | ✗ `B-6010` |
| postgres-ledger (config) | `B-5011` | `B-6011` | ✓ 79% | ✓ `B-5011` | ✓ `B-5011` |
| search-index (migration) | `B-5012` | `B-6012` | ✓ 91% | ✓ `B-5012` | ✓ `B-5012` |
| session-store (migration) | `B-5013` | `B-6013` | ✓ 81% | ✓ `B-5013` | ✓ `B-5013` |
| feature-flags (flag) | `B-5014` | `B-6014` | ✓ 77% | ✗ `B-6014` | ✓ `B-5014` |
| sanctions-screening (deploy) | `B-5015` | `B-6015` | ✓ 83% | ✗ `B-6015` | ✓ `sanctions-screening` |

Weights were set before the benchmark was written and were not tuned against it.
