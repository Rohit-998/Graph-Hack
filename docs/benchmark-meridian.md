# RCA benchmark

16 scenarios generated from the meridian topology (`firebreak/benchmark.py`, seed 7). Each has one real cause and one decoy change on a component no alerting service depends on. In 10 of them the decoy is more recent than the real cause (or the cause is a vendor outage with no change at all).

| Method | Top-1 accuracy | LLM calls / incident |
|---|---|---|
| **Firebreak** (graph RCA, deterministic) | **100%** | 0 |
| Most recent change | 38% | 0 |
| Flat-context LLM (gemini-3.5-flash-lite, no topology) | 88% | 1 |

The flat-LLM baseline is scored leniently: naming the right component counts as correct even without the change id. It sees the same alerts and changes Firebreak does, but not the dependency graph.

Median Firebreak time to verdict: 0.166s (full agent loop, incl. graph writes).

| Scenario | Real cause | Decoy | Firebreak | Most recent | Flat LLM |
|---|---|---|---|---|---|
| rec-api (deploy) | `B-5000` | `B-6000` | ✓ 90% | ✓ `B-5000` | ✓ `rec-api` |
| user-profile (config) | `B-5001` | `B-6001` | ✓ 92% | ✗ `B-6001` | ✓ `user-profile` |
| manifest-service (config) | `B-5002` | `B-6002` | ✓ 95% | ✗ `B-6002` | ✓ `B-5002` |
| stripe (vendor outage) | `stripe` | `B-6003` | ✓ 91% | ✗ `B-6003` | ✗ `B-6003` |
| feature-store (config) | `B-5004` | `B-6004` | ✓ 91% | ✗ `B-6004` | ✓ `B-5004` |
| embedding-index (migration) | `B-5005` | `B-6005` | ✓ 92% | ✓ `B-5005` | ✓ `B-5005` |
| postgres-ledger (config) | `B-5006` | `B-6006` | ✓ 90% | ✗ `B-6006` | ✓ `postgres-ledger` |
| fraud-service (flag) | `B-5007` | `B-6007` | ✓ 92% | ✗ `B-6007` | ✓ `fraud-service` |
| drm-licence-service (deploy) | `B-5008` | `B-6008` | ✓ 91% | ✗ `B-6008` | ✓ `B-5008` |
| playback-manager (flag) | `B-5009` | `B-6009` | ✓ 90% | ✓ `B-5009` | ✓ `playback-manager` |
| entitlement-service (config) | `B-5010` | `B-6010` | ✓ 92% | ✓ `B-5010` | ✓ `entitlement-service` |
| session-store (config) | `B-5011` | `B-6011` | ✓ 90% | ✓ `B-5011` | ✓ `B-5011` |
| search-index-shim (flag) | `B-5012` | `B-6012` | ✓ 90% | ✗ `B-6012` | ✗ `None` |
| clickhouse-events (config) | `B-5013` | `B-6013` | ✓ 91% | ✗ `B-6013` | ✓ `clickhouse-events` |
| model-server (flag) | `B-5014` | `B-6014` | ✓ 90% | ✗ `B-6014` | ✓ `B-5014` |
| auth-service (deploy) | `B-5015` | `B-6015` | ✓ 91% | ✓ `B-5015` | ✓ `B-5015` |

Weights were set before the benchmark was written and were not tuned against it.
