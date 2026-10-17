# RCA benchmark

16 scenarios generated from the meridian topology (`firebreak/benchmark.py`, seed 7). Each has one real cause and one decoy change on a component no alerting service depends on. In 10 of them the decoy is more recent than the real cause (or the cause is a vendor outage with no change at all).

| Method | Top-1 accuracy | LLM calls / incident |
|---|---|---|
| **Firebreak** (graph RCA, deterministic) | **100%** | 0 |
| Most recent change | 31% | 0 |

Median Firebreak time to verdict: 0.161s (full agent loop, incl. graph writes).

| Scenario | Real cause | Decoy | Firebreak | Most recent |
|---|---|---|---|---|
| rec-api (deploy) | `B-5000` | `C-8193` | ✓ 100% | ✓ `B-5000` |
| user-profile (config) | `B-5001` | `C-7953` | ✓ 100% | ✓ `B-5001` |
| manifest-service (config) | `B-5002` | `C-8036` | ✓ 100% | ✗ `C-8036` |
| stripe (vendor outage) | `stripe` | `C-8253` | ✓ 100% | ✗ `C-8253` |
| feature-store (config) | `B-5004` | `C-8327` | ✓ 100% | ✗ `C-8327` |
| embedding-index (migration) | `B-5005` | `C-8046` | ✓ 100% | ✗ `C-8046` |
| postgres-ledger (config) | `B-5006` | `C-8188` | ✓ 100% | ✗ `C-8188` |
| fraud-service (flag) | `B-5007` | `C-8344` | ✓ 100% | ✓ `B-5007` |
| drm-licence-service (deploy) | `B-5008` | `C-8049` | ✓ 100% | ✗ `C-8049` |
| playback-manager (flag) | `B-5009` | `C-8528` | ✓ 59% | ✓ `B-5009` |
| entitlement-service (config) | `B-5010` | `C-7927` | ✓ 100% | ✓ `B-5010` |
| session-store (config) | `B-5011` | `C-7715` | ✓ 100% | ✗ `C-7715` |
| search-index-shim (flag) | `B-5012` | `C-8181` | ✓ 57% | ✗ `C-8181` |
| clickhouse-events (config) | `B-5013` | `C-8191` | ✓ 100% | ✗ `C-8191` |
| model-server (flag) | `B-5014` | `C-8376` | ✓ 100% | ✗ `C-8376` |
| auth-service (deploy) | `B-5015` | `C-7737` | ✓ 100% | ✗ `C-7737` |

Weights were set before the benchmark was written and were not tuned against it.
