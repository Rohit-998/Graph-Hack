# RCA benchmark

16 scenarios generated from the meridian topology (`firebreak/benchmark.py`, seed 7). Each has one real cause and one decoy change on a component no alerting service depends on. In 10 of them the decoy is more recent than the real cause (or the cause is a vendor outage with no change at all).

| Method | Top-1 accuracy | LLM calls / incident |
|---|---|---|
| **Firebreak** (graph RCA, deterministic) | **100%** | 0 |
| Most recent change | 12% | 0 |

Median Firebreak time to verdict: 0.162s (full agent loop, incl. graph writes).

| Scenario | Real cause | Decoy | Firebreak | Most recent |
|---|---|---|---|---|
| rec-api (deploy) | `B-5000` | `C-7873` | ✓ 100% | ✓ `B-5000` |
| user-profile (config) | `B-5001` | `C-8507` | ✓ 100% | ✗ `C-8507` |
| manifest-service (config) | `B-5002` | `C-7887` | ✓ 76% | ✗ `C-7887` |
| stripe (vendor outage) | `stripe` | `C-7842` | ✓ 100% | ✗ `C-7842` |
| feature-store (config) | `B-5004` | `C-8063` | ✓ 100% | ✗ `C-8063` |
| embedding-index (migration) | `B-5005` | `C-8144` | ✓ 100% | ✗ `C-8144` |
| postgres-ledger (config) | `B-5006` | `C-7983` | ✓ 100% | ✗ `C-7983` |
| fraud-service (flag) | `B-5007` | `C-8110` | ✓ 100% | ✓ `B-5007` |
| drm-licence-service (deploy) | `B-5008` | `C-8188` | ✓ 100% | ✗ `C-8188` |
| playback-manager (flag) | `B-5009` | `C-8324` | ✓ 64% | ✗ `C-8324` |
| entitlement-service (config) | `B-5010` | `C-7722` | ✓ 100% | ✗ `C-7722` |
| session-store (config) | `B-5011` | `C-8676` | ✓ 100% | ✗ `C-8676` |
| search-index-shim (flag) | `B-5012` | `C-8068` | ✓ 54% | ✗ `C-8068` |
| clickhouse-events (config) | `B-5013` | `C-8672` | ✓ 100% | ✗ `C-8672` |
| model-server (flag) | `B-5014` | `C-8610` | ✓ 100% | ✗ `C-8610` |
| auth-service (deploy) | `B-5015` | `C-7752` | ✓ 100% | ✗ `C-7752` |

Weights were set before the benchmark was written and were not tuned against it.
