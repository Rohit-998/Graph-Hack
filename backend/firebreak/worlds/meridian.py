"""Second synthetic world: Meridian, a media streaming and recommendations platform.

Same interface as `nimbuspay` (see package docstring), different domain and
different topology shape: a fan-out of clients onto a streaming tier, then
recommendation/data pipelines, with per-region shards instead of one core OLTP
database. Nothing in the engine is NimbusPay-specific; this world exists to prove
the RCA engine is generic, not tuned to one demo.

The four chaos-component names are deliberately shared with NimbusPay
(`auth-service`, `stripe`, `risk-scoring`, `postgres-ledger`) so the same
scenario definitions run unchanged against a different graph.
"""

MIN = 60_000
HOUR = 60 * MIN
DAY = 24 * HOUR

TEAMS = [
    ("streaming", "#team-streaming", "Playback, transcoding and delivery"),
    ("identity", "#team-identity", "Accounts, sessions, entitlements and DRM"),
    ("recommendations", "#team-recs", "Ranking, features and personalisation"),
    ("data-platform", "#team-data", "Ingest, warehouses and analytics"),
    ("apps", "#team-apps", "Web, TV and mobile clients"),
    ("trust", "#team-trust", "Billing risk, abuse and fraud"),
]

PEOPLE = [
    ("yara", "Yara Haddad", "VP Engineering", "Europe/Berlin", None, None),
    ("felix", "Felix Andersen", "Engineering Manager", "Europe/Copenhagen", "streaming", "lead"),
    ("ines", "Inês Duarte", "Staff Engineer", "Europe/Lisbon", "streaming", "member"),
    ("kwame", "Kwame Mensah", "Site Reliability Engineer", "Africa/Accra", "streaming", "member"),
    ("rohan", "Rohan Bhat", "Engineering Manager", "Asia/Kolkata", "identity", "lead"),
    ("priya", "Priya Raman", "Senior Software Engineer", "Asia/Kolkata", "identity", "member"),
    ("marcus", "Marcus Chen", "Site Reliability Engineer", "America/Los_Angeles", "identity", "member"),
    ("lars", "Lars Eriksen", "Engineering Manager", "Europe/Oslo", "recommendations", "lead"),
    ("ivan", "Ivan Petrov", "ML Engineer", "Europe/Sofia", "recommendations", "member"),
    ("zara", "Zara Ahmed", "Software Engineer", "Europe/London", "recommendations", "member"),
    ("kenji", "Kenji Sato", "Engineering Manager", "Asia/Tokyo", "data-platform", "lead"),
    ("maya", "Maya Patel", "Database Engineer", "America/New_York", "data-platform", "member"),
    ("omar", "Omar Haddad", "Site Reliability Engineer", "Asia/Dubai", "data-platform", "member"),
    ("lena", "Lena Fischer", "Engineering Manager", "Europe/Berlin", "apps", "lead"),
    ("ravi", "Ravi Iyer", "Software Engineer", "Asia/Kolkata", "apps", "member"),
    ("chloe", "Chloe Martin", "Software Engineer", "Europe/Paris", "apps", "member"),
    ("noor", "Noor Khan", "Engineering Manager", "Asia/Karachi", "trust", "lead"),
    ("tomas", "Tomás Silva", "Software Engineer", "Europe/Lisbon", "trust", "member"),
    ("ben", "Ben Carter", "Software Engineer", "America/Chicago", "apps", "member"),
]

ON_CALL = {
    "streaming": ("kwame", "ines"),
    "identity": ("marcus", "priya"),
    "recommendations": ("ivan", "zara"),
    "data-platform": ("omar", "maya"),
    "apps": ("ravi", "chloe"),
    "trust": ("tomas", "noor"),
}

# name, kind, tier, owner team, language, description, customer_facing
COMPONENTS = [
    # apps / clients (entry points)
    ("tv-app-api", "Service", 1, "apps", "Kotlin", "Smart-TV and console API", True),
    ("mobile-app-api", "Service", 1, "apps", "Kotlin", "iOS and Android API", True),
    ("web-player-api", "Service", 1, "apps", "TypeScript", "Browser player API", True),
    ("search-api", "Service", 2, "apps", "Go", "Title and people search", True),
    # streaming
    ("playback-manager", "Service", 1, "streaming", "Go", "Session leases and manifest selection", False),
    ("drm-licence-service", "Service", 1, "streaming", "Java", "Widevine and FairPlay licences", False),
    ("transcode-pipeline", "Service", 2, "streaming", "Python", "Per-title encode jobs", False),
    ("cdn", "Vendor", 1, "streaming", None, "Global CDN for segmented media", False),
    ("origin-shield", "Service", 2, "streaming", "Go", "Origin request coalescing and auth", False),
    ("manifest-service", "Service", 1, "streaming", "Go", "HLS/DASH manifest generation", False),
    # identity (shares the auth-service name with NimbusPay so chaos scenarios reuse it)
    ("auth-service", "Service", 1, "identity", "Go", "OAuth and session tokens", False),
    ("entitlement-service", "Service", 1, "identity", "Kotlin", "Tier and geo entitlements", False),
    ("session-store", "Datastore", 1, "identity", "Redis", "Session and refresh-token store", False),
    ("user-profile", "Service", 2, "identity", "Kotlin", "Profiles and watchlists", False),
    # recommendations
    ("rec-api", "Service", 1, "recommendations", "Python", "Home rows and next-play ranking", False),
    ("feature-store", "Service", 1, "recommendations", "Python", "Online feature lookup", False),
    ("embedding-index", "Datastore", 2, "recommendations", "Milvus", "Title embeddings for retrieval", False),
    ("model-server", "Service", 1, "recommendations", "Python", "Ranking model inference", False),
    ("ranking-model", "Vendor", 2, "recommendations", None, "Hosted ranking model endpoint", False),
    # data platform
    ("postgres-ledger", "Datastore", 1, "data-platform", "PostgreSQL", "Subscription and billing ledger", False),
    ("clickhouse-events", "Datastore", 2, "data-platform", "ClickHouse", "Viewing events warehouse", False),
    ("kafka-events", "Queue", 1, "data-platform", "Kafka", "Event bus for playback and billing", False),
    ("ingest-service", "Service", 2, "data-platform", "Go", "Event validation into kafka-events", False),
    ("batch-etl", "Service", 3, "data-platform", "Spark", "Nightly warehouse transforms", False),
    ("metrics-aggregator", "Service", 2, "data-platform", "Python", "Rollups for dashboards", False),
    # trust (risk-scoring shared with NimbusPay for the flag scenario)
    ("risk-scoring", "Service", 1, "trust", "Python", "Payment and account-takeover risk", False),
    ("fraud-service", "Service", 1, "trust", "Python", "Real-time abuse checks", False),
    ("stripe", "Vendor", 1, "trust", None, "Subscription billing provider", False),
    # infra placement
    ("k8s-prod-a", "Cluster", 1, "data-platform", None, "Primary Kubernetes cluster (eu-west-1a)", False),
    ("k8s-prod-b", "Cluster", 1, "data-platform", None, "Secondary Kubernetes cluster (eu-west-1b)", False),
]

# (caller, dependency, mode, protocol)
DEPENDS_ON = [
    ("tv-app-api", "playback-manager", "sync", "grpc"),
    ("tv-app-api", "search-api", "sync", "http"),
    ("mobile-app-api", "playback-manager", "sync", "grpc"),
    ("mobile-app-api", "rec-api", "sync", "http"),
    ("mobile-app-api", "auth-service", "sync", "grpc"),
    ("web-player-api", "manifest-service", "sync", "http"),
    ("web-player-api", "auth-service", "sync", "grpc"),
    ("web-player-api", "rec-api", "sync", "http"),
    ("search-api", "search-index-shim", "sync", "http"),
    ("search-api", "entitlement-service", "sync", "grpc"),
    ("playback-manager", "manifest-service", "sync", "grpc"),
    ("playback-manager", "drm-licence-service", "sync", "grpc"),
    ("playback-manager", "entitlement-service", "sync", "grpc"),
    ("playback-manager", "cdn", "sync", "https"),
    ("playback-manager", "kafka-events", "async", "kafka"),
    ("manifest-service", "origin-shield", "sync", "http"),
    ("manifest-service", "transcode-pipeline", "async", "kafka"),
    ("drm-licence-service", "auth-service", "sync", "grpc"),
    ("drm-licence-service", "session-store", "sync", "redis"),
    ("auth-service", "entitlement-service", "sync", "grpc"),
    ("auth-service", "session-store", "sync", "redis"),
    ("auth-service", "postgres-ledger", "sync", "sql"),
    ("entitlement-service", "user-profile", "sync", "grpc"),
    ("entitlement-service", "stripe", "sync", "https"),
    # Abuse checks gate entitlements, so a risk regression reaches playback.
    ("entitlement-service", "fraud-service", "sync", "grpc"),
    ("user-profile", "postgres-ledger", "sync", "sql"),
    ("rec-api", "feature-store", "sync", "grpc"),
    ("rec-api", "model-server", "sync", "grpc"),
    ("rec-api", "embedding-index", "sync", "http"),
    ("feature-store", "clickhouse-events", "sync", "http"),
    ("model-server", "ranking-model", "sync", "https"),
    ("model-server", "embedding-index", "sync", "http"),
    ("fraud-service", "risk-scoring", "sync", "grpc"),
    ("fraud-service", "clickhouse-events", "sync", "http"),
    ("risk-scoring", "clickhouse-events", "sync", "http"),
    ("risk-scoring", "postgres-ledger", "sync", "sql"),
    ("ingest-service", "kafka-events", "async", "kafka"),
    ("ingest-service", "clickhouse-events", "sync", "http"),
    ("batch-etl", "clickhouse-events", "sync", "sql"),
    ("batch-etl", "postgres-ledger", "sync", "sql"),
    ("metrics-aggregator", "clickhouse-events", "sync", "sql"),
    ("metrics-aggregator", "kafka-events", "async", "kafka"),
]

# search-api points at a shim that is itself a component; keep the edge inside the world.
COMPONENTS.append(("search-index-shim", "Service", 2, "apps", "Go", "Search index facade", False))
DEPENDS_ON.append(("search-index-shim", "embedding-index", "sync", "http"))

FAILS_OVER_TO = [("cdn", "origin-shield")]

# Which component this world faults for each chaos scenario.
SCENARIO_ROOTS = {
    "bad-deploy": "auth-service",
    "vendor-outage": "cdn",          # the vendor with a failover path, mirroring stripe -> adyen
    "flag-regression": "risk-scoring",
    "db-migration-lock": "postgres-ledger",
}

RUNS_ON_B = {"batch-etl", "metrics-aggregator", "ingest-service", "search-api"}

BASELINE = {1: (90, 0.002, 900), 2: (220, 0.004, 300), 3: (600, 0.008, 20)}

PRODUCTS = [
    ("Streaming Playback", "Movies and series playback on all devices", ["tv-app-api", "mobile-app-api", "web-player-api"]),
    ("Discovery", "Home rows, search and next-play", ["search-api", "rec-api"]),
    ("Subscriptions", "Plans, billing and entitlements", ["entitlement-service"]),
    ("Creator Analytics", "Per-title performance for studios", ["metrics-aggregator"]),
]

CUSTOMERS = [
    ("CUST-101", "Northwind Studios", "enterprise", 3_600_000, 99.95,
     {"Streaming Playback": 18_000, "Discovery": 0, "Creator Analytics": 0}),
    ("CUST-102", "Bluewave Telco", "enterprise", 2_200_000, 99.95,
     {"Streaming Playback": 11_500, "Subscriptions": 4_000}),
    ("CUST-103", "Kite Sports", "growth", 540_000, 99.9,
     {"Streaming Playback": 6_200, "Discovery": 1_100}),
    ("CUST-104", "Pixel Devices", "growth", 380_000, 99.9,
     {"Discovery": 900, "Subscriptions": 2_300}),
    ("CUST-105", "Atlas Airlines", "enterprise", 900_000, 99.95,
     {"Subscriptions": 3_100, "Creator Analytics": 0}),
]

DECISIONS = [
    {"id": "ADR-031", "title": "Licence every DRM play through auth-service", "status": "accepted", "days_ago": 330,
     "context": "Geo and tier changes must take effect immediately for licensed content.",
     "decision": "drm-licence-service introspects the session against auth-service on every licence request.",
     "consequences": "auth-service is a hard dependency of playback. An auth regression stops all licensed playback.",
     "about": ["drm-licence-service", "auth-service", "session-store"], "decided_by": ["rohan", "priya"], "threads": ["T-201"]},
    {"id": "ADR-036", "title": "CDN as the only egress path", "status": "accepted", "days_ago": 260,
     "context": "Multiple egress paths made cost and abuse hard to attribute.",
     "decision": "All media egress goes through cdn; origin-shield protects origin and fails over within the CDN.",
     "consequences": "A CDN incident is a playback incident for every device at once.",
     "about": ["cdn", "origin-shield", "playback-manager"], "decided_by": ["felix", "ines"], "threads": ["T-202"]},
    {"id": "ADR-040", "title": "Online features from ClickHouse, not the transaction database", "status": "accepted", "days_ago": 180,
     "context": "Feature lookups were saturating the billing database.",
     "decision": "rec-api reads features from feature-store backed by clickhouse-events.",
     "consequences": "Recommendation freshness now depends on event ingest lag, not DB load.",
     "about": ["feature-store", "clickhouse-events", "rec-api"], "decided_by": ["lars", "ivan"], "threads": ["T-203"]},
    {"id": "ADR-044", "title": "Risk model rollouts behind feature flags", "status": "accepted", "days_ago": 120,
     "context": "A ranking-model change once charged declined cards for an hour.",
     "decision": "risk-scoring and model-server rollouts go through flags with kill switches.",
     "consequences": "A bad flag is the fastest way to break billing risk checks.",
     "about": ["risk-scoring", "model-server", "fraud-service"], "decided_by": ["noor", "ivan"], "threads": ["T-204"]},
    {"id": "ADR-047", "title": "Separate ledger database from analytics", "status": "accepted", "days_ago": 90,
     "context": "Analytics queries on the billing database caused lock contention.",
     "decision": "postgres-ledger holds subscriptions only; analytics live in clickhouse-events.",
     "consequences": "Migrations on postgres-ledger must be online; a lock stalls auth, entitlements and billing.",
     "about": ["postgres-ledger", "clickhouse-events", "batch-etl"], "decided_by": ["kenji", "maya"], "threads": ["T-205"]},
]

RUNBOOKS = [
    {"id": "RB-201", "title": "Roll back auth-service",
     "body": "1. Confirm licence 5xx on drm-licence-service. 2. `deployctl rollback auth-service`. 3. Watch licence p95 fall below 120ms.",
     "covers": ["auth-service", "session-store"], "wrote": "priya"},
    {"id": "RB-202", "title": "Fail playback over to origin-shield",
     "body": "1. Check cdn error rate. 2. `streamctl egress set origin-shield`. 3. Verify manifest 200s per device class.",
     "covers": ["cdn", "origin-shield", "playback-manager"], "wrote": "ines"},
    {"id": "RB-203", "title": "Turn off a risk flag",
     "body": "1. Find the flag in recent changes on risk-scoring. 2. `flags off <flag> --env prod`. 3. Confirm charge failure rate drops.",
     "covers": ["risk-scoring", "fraud-service"], "wrote": "ivan"},
    {"id": "RB-204", "title": "Cancel a blocking migration",
     "body": "1. `SELECT * FROM pg_locks WHERE granted = false`. 2. pg_cancel_backend the migration. 3. Re-run online.",
     "covers": ["postgres-ledger"], "wrote": "maya"},
    {"id": "RB-205", "title": "Drain a lagging Kafka consumer",
     "body": "1. Check consumer lag per partition. 2. Scale the lagging consumer group. 3. Page data-platform if brokers are unhealthy.",
     "covers": ["kafka-events"], "wrote": "omar"},
]

THREADS = [
    {"id": "T-201", "channel": "#architecture", "days_ago": 332, "author": "priya",
     "title": "Why every DRM licence calls auth",
     "body": "Rohan and I agreed that entitlement changes must apply on the next licence request, not after a 15 minute token cache.",
     "mentions": ["auth-service", "drm-licence-service"]},
    {"id": "T-202", "channel": "#team-streaming", "days_ago": 262, "author": "ines",
     "title": "Single CDN egress",
     "body": "One egress path means CDN incidents are playback incidents. We accepted that for cost clarity.",
     "mentions": ["cdn", "origin-shield"]},
    {"id": "T-203", "channel": "#team-recs", "days_ago": 182, "author": "ivan",
     "title": "Feature store backed by ClickHouse",
     "body": "Nightly batch features replaced online lookups on postgres-ledger. Freshness is now ingest-lag bound.",
     "mentions": ["feature-store", "clickhouse-events"]},
    {"id": "T-204", "channel": "#team-trust", "days_ago": 122, "author": "noor",
     "title": "Every risk model rollout needs a kill switch",
     "body": "After the declined-card incident, all model-server and risk-scoring changes ship behind flags.",
     "mentions": ["risk-scoring", "model-server"]},
    {"id": "T-205", "channel": "#team-data", "days_ago": 92, "author": "kenji",
     "title": "Splitting the ledger out",
     "body": "Analytics joins against the billing DB took locks. Ledger is its own Postgres now.",
     "mentions": ["postgres-ledger", "clickhouse-events"]},
    {"id": "T-206", "channel": "#incidents", "days_ago": 60, "author": "kwame",
     "title": "INC-3108 playback start failures",
     "body": "auth-service v4.2.0 leaked connection handles, licence calls timed out for 18% of sessions. Rolled back.",
     "mentions": ["auth-service", "drm-licence-service", "playback-manager"]},
    {"id": "T-207", "channel": "#incidents", "days_ago": 40, "author": "maya",
     "title": "INC-3121 entitlements blocked by migration",
     "body": "ALTER TABLE on subscriptions held ACCESS EXCLUSIVE. Cancelled the migration.",
     "mentions": ["postgres-ledger", "entitlement-service"]},
    {"id": "T-208", "channel": "#team-apps", "days_ago": 25, "author": "ravi",
     "title": "Search shim",
     "body": "search-api now fronts embedding-index through a shim so we can swap retrieval without app releases.",
     "mentions": ["search-api", "embedding-index"]},
]

EXPERT_IN = [
    ("priya", "auth-service", 0.9), ("marcus", "session-store", 0.7), ("rohan", "auth-service", 0.6),
    ("ines", "cdn", 0.9), ("kwame", "playback-manager", 0.8), ("felix", "playback-manager", 0.7),
    ("ivan", "model-server", 0.9), ("ivan", "risk-scoring", 0.7), ("zara", "feature-store", 0.6),
    ("lars", "model-server", 0.7), ("maya", "postgres-ledger", 0.9), ("omar", "kafka-events", 0.8),
    ("kenji", "batch-etl", 0.8), ("ravi", "search-api", 0.7), ("tomas", "fraud-service", 0.6),
    ("noor", "risk-scoring", 0.8),
]

# root: ("change", component, kind, version, summary, author) or ("component", component)
INCIDENTS = [
    {"id": "INC-3108", "days_ago": 60, "severity": "SEV1", "title": "Playback start failures on licensed titles",
     "summary": "auth-service v4.2.0 leaked connection handles; licence requests timed out. Rolled back in 7 minutes.",
     "root": ("change", "auth-service", "deploy", "v4.2.0", "New token introspection pool", "priya"),
     "affected": ["auth-service", "drm-licence-service", "playback-manager", "tv-app-api"],
     "responders": ["kwame", "priya"], "action": "rollback", "ttm_min": 7},
    {"id": "INC-3112", "days_ago": 52, "severity": "SEV1", "title": "CDN error spike in one region",
     "summary": "cdn returned 5xx for EU. Failed over to origin-shield per ADR-036.",
     "root": ("component", "cdn"), "affected": ["cdn", "playback-manager", "origin-shield"],
     "responders": ["ines", "felix"], "action": "failover", "ttm_min": 16},
    {"id": "INC-3117", "days_ago": 45, "severity": "SEV2", "title": "Home rows slow for mobile",
     "summary": "Feature-store lookups timed out after an index rebuild. Rebuilt online.",
     "root": ("change", "clickhouse-events", "config", "cfg-31", "Rebuild feature rollups", "kenji"),
     "affected": ["clickhouse-events", "feature-store", "rec-api", "mobile-app-api"],
     "responders": ["kenji", "ivan"], "action": "rollback", "ttm_min": 20},
    {"id": "INC-3121", "days_ago": 40, "severity": "SEV2", "title": "Entitlements blocked by migration",
     "summary": "Migration on subscriptions held ACCESS EXCLUSIVE; entitlements stalled. Cancelled.",
     "root": ("change", "postgres-ledger", "migration", "m-0710", "Add plan_overrides to subscriptions", "maya"),
     "affected": ["postgres-ledger", "entitlement-service", "auth-service"],
     "responders": ["maya"], "action": "rollback", "ttm_min": 15},
    {"id": "INC-3126", "days_ago": 33, "severity": "SEV2", "title": "Card declines spike",
     "summary": "Risk flag enabled a stricter model; healthy cards declined. Flag off.",
     "root": ("change", "risk-scoring", "flag", "trust.strict-v5", "Enable strict risk model", "ivan"),
     "affected": ["risk-scoring", "fraud-service", "entitlement-service"],
     "responders": ["ivan", "noor"], "action": "flag_off", "ttm_min": 11},
    {"id": "INC-3130", "days_ago": 28, "severity": "SEV3", "title": "Viewing metrics delayed",
     "summary": "kafka-events consumer lag after broker restart. Scaled consumers.",
     "root": ("component", "kafka-events"), "affected": ["kafka-events", "metrics-aggregator", "ingest-service"],
     "responders": ["omar"], "action": "scale", "ttm_min": 30},
    {"id": "INC-3136", "days_ago": 22, "severity": "SEV2", "title": "Manifest 500s on TV",
     "summary": "manifest-service v2.10.0 mishandled range requests. Rolled back.",
     "root": ("change", "manifest-service", "deploy", "v2.10.0", "Streaming range parsing", "chloe"),
     "affected": ["manifest-service", "web-player-api", "tv-app-api"],
     "responders": ["chloe", "lena"], "action": "rollback", "ttm_min": 9},
    {"id": "INC-3141", "days_ago": 18, "severity": "SEV3", "title": "Search returns stale titles",
     "summary": "embedding-index compaction paused. Resumed compaction.",
     "root": ("component", "embedding-index"), "affected": ["embedding-index", "search-index-shim", "search-api"],
     "responders": ["ravi"], "action": "restart", "ttm_min": 25},
    {"id": "INC-3145", "days_ago": 14, "severity": "SEV2", "title": "Login loop on mobile",
     "summary": "Session store eviction policy changed; sessions dropped. Config reverted.",
     "root": ("change", "session-store", "config", "cfg-44", "Reduce session TTL", "marcus"),
     "affected": ["session-store", "auth-service", "mobile-app-api"],
     "responders": ["marcus", "rohan"], "action": "rollback", "ttm_min": 10},
    {"id": "INC-3150", "days_ago": 10, "severity": "SEV2", "title": "Ranking service latency",
     "summary": "model-server cold starts after a scale-down. Pre-warmed instances.",
     "root": ("change", "model-server", "config", "cfg-51", "Scale to zero at night", "lars"),
     "affected": ["model-server", "rec-api", "mobile-app-api"],
     "responders": ["lars", "ivan"], "action": "rollback", "ttm_min": 13},
    {"id": "INC-3154", "days_ago": 6, "severity": "SEV3", "title": "Billing webhook delays",
     "summary": "stripe webhook backlog. Paged vendor, drained queue.",
     "root": ("component", "stripe"), "affected": ["stripe", "entitlement-service", "batch-etl"],
     "responders": ["tomas"], "action": "page", "ttm_min": 40},
    {"id": "INC-3158", "days_ago": 3, "severity": "SEV2", "title": "Nightly ETL overran",
     "summary": "batch-etl job scanned without partition pruning. Killed and re-ran with filters.",
     "root": ("change", "batch-etl", "config", "cfg-58", "Widen lookback window", "kenji"),
     "affected": ["batch-etl", "clickhouse-events"],
     "responders": ["kenji", "omar"], "action": "rollback", "ttm_min": 12},
]

BACKGROUND_CHANGE_COUNT = 58
CHANGE_KINDS = ["deploy", "deploy", "deploy", "config", "flag", "migration"]
