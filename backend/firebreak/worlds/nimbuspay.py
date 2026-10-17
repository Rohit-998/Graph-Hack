"""Synthetic world for the NimbusPay tenant (100% fabricated data).

Pure data, no I/O. `seed.py` turns this into nodes and edges in FalkorDB.
Times are expressed as offsets from "now" so the world is always fresh.
"""

MIN = 60_000          # ms
HOUR = 60 * MIN
DAY = 24 * HOUR

# --- Org -------------------------------------------------------------------

TEAMS = [
    # name, slack channel, mission
    ("identity", "#team-identity", "Authentication, sessions, user accounts and KYC"),
    ("payments", "#team-payments", "Checkout, payment processing, ledger and payouts"),
    ("edge-platform", "#team-edge", "Customer-facing frontends and BFFs"),
    ("data-platform", "#team-data", "Databases, caches, streaming and reporting"),
    ("growth", "#team-growth", "Catalog, search and notifications"),
    ("risk", "#team-risk", "Fraud detection, risk scoring and sanctions screening"),
]

PEOPLE = [
    # id, name, title, timezone, team, role
    ("elena", "Elena Vogel", "VP Engineering", "Europe/Berlin", None, None),
    ("aisha", "Aisha Bello", "Engineering Manager", "Africa/Lagos", "identity", "lead"),
    ("priya", "Priya Raman", "Senior Software Engineer", "Asia/Kolkata", "identity", "member"),
    ("marcus", "Marcus Chen", "Site Reliability Engineer", "America/Los_Angeles", "identity", "member"),
    ("diego", "Diego Alvarez", "Engineering Manager", "America/Mexico_City", "payments", "lead"),
    ("hana", "Hana Kim", "Staff Software Engineer", "Asia/Seoul", "payments", "member"),
    ("tom", "Tom Okafor", "Software Engineer", "Europe/London", "payments", "member"),
    ("lena", "Lena Fischer", "Engineering Manager", "Europe/Berlin", "edge-platform", "lead"),
    ("ravi", "Ravi Iyer", "Software Engineer", "Asia/Kolkata", "edge-platform", "member"),
    ("sofia", "Sofia Rossi", "Site Reliability Engineer", "Europe/Rome", "edge-platform", "member"),
    ("kenji", "Kenji Sato", "Engineering Manager", "Asia/Tokyo", "data-platform", "lead"),
    ("maya", "Maya Patel", "Database Engineer", "America/New_York", "data-platform", "member"),
    ("omar", "Omar Haddad", "Site Reliability Engineer", "Asia/Dubai", "data-platform", "member"),
    ("chloe", "Chloe Martin", "Engineering Manager", "Europe/Paris", "growth", "lead"),
    ("arjun", "Arjun Mehta", "Software Engineer", "Asia/Kolkata", "growth", "member"),
    ("ben", "Ben Carter", "Software Engineer", "America/Chicago", "growth", "member"),
    ("noor", "Noor Khan", "Engineering Manager", "Asia/Karachi", "risk", "lead"),
    ("ivan", "Ivan Petrov", "ML Engineer", "Europe/Sofia", "risk", "member"),
    ("zara", "Zara Ahmed", "Software Engineer", "Europe/London", "risk", "member"),
]

# Primary (level 1) and secondary (level 2) on-call per team, for the current rotation.
ON_CALL = {
    "identity": ("marcus", "priya"),
    "payments": ("tom", "hana"),
    "edge-platform": ("sofia", "ravi"),
    "data-platform": ("omar", "maya"),
    "growth": ("ben", "arjun"),
    "risk": ("zara", "ivan"),
}

# --- Topology ----------------------------------------------------------------

# name, kind (sub-label), tier, owner team, language, description, customer_facing
COMPONENTS = [
    # edge
    ("web-bff", "Service", 1, "edge-platform", "TypeScript", "Backend-for-frontend for the web checkout", True),
    ("mobile-bff", "Service", 1, "edge-platform", "TypeScript", "Backend-for-frontend for the mobile wallet app", True),
    ("merchant-dashboard", "Service", 2, "edge-platform", "TypeScript", "Merchant-facing dashboard API", True),
    # payments
    ("checkout-api", "Service", 1, "payments", "Go", "Creates and confirms checkout sessions", True),
    ("payouts-api", "Service", 1, "payments", "Go", "Merchant payouts and balance API", True),
    ("payments-core", "Service", 1, "payments", "Go", "Payment orchestration across acquirers", False),
    ("ledger-service", "Service", 1, "payments", "Java", "Double-entry ledger of all money movement", False),
    ("refunds-service", "Service", 2, "payments", "Go", "Refund processing", False),
    ("billing-service", "Service", 2, "payments", "Java", "Merchant fee invoicing", False),
    # identity
    ("auth-service", "Service", 1, "identity", "Go", "Token issuance and introspection", False),
    ("user-service", "Service", 1, "identity", "Kotlin", "User and merchant account records", False),
    ("kyc-service", "Service", 2, "identity", "Kotlin", "Know-your-customer verification", False),
    ("session-store", "Datastore", 1, "identity", "Redis", "Session and refresh-token store", False),
    # data platform
    ("postgres-main", "Datastore", 1, "data-platform", "PostgreSQL", "Primary OLTP database", False),
    ("postgres-ledger", "Datastore", 1, "data-platform", "PostgreSQL", "Dedicated ledger database", False),
    ("redis-cache", "Datastore", 2, "data-platform", "Redis", "Shared read-through cache", False),
    ("search-index", "Datastore", 2, "data-platform", "OpenSearch", "Full-text product index", False),
    ("kafka-events", "Queue", 1, "data-platform", "Kafka", "Domain event bus", False),
    ("reporting-service", "Service", 3, "data-platform", "Python", "Merchant reports and exports", False),
    ("feature-flags", "Service", 1, "edge-platform", "Go", "Server-side feature flag evaluation", False),
    # growth
    ("search-service", "Service", 2, "growth", "Python", "Product and merchant search", False),
    ("catalog-service", "Service", 2, "growth", "Kotlin", "Merchant product catalog", False),
    ("notifications-service", "Service", 2, "growth", "TypeScript", "Push and SMS notifications", False),
    ("email-worker", "Service", 3, "growth", "Python", "Transactional email sender", False),
    # risk
    ("fraud-service", "Service", 1, "risk", "Python", "Real-time fraud checks on checkout", False),
    ("risk-scoring", "Service", 1, "risk", "Python", "ML risk model serving", False),
    ("sanctions-screening", "Service", 2, "risk", "Java", "Sanctions list screening", False),
    # external vendors
    ("stripe", "Vendor", 1, "payments", None, "Primary card acquirer", False),
    ("adyen", "Vendor", 1, "payments", None, "Secondary card acquirer (failover)", False),
    ("twilio", "Vendor", 3, "growth", None, "SMS delivery", False),
    ("sendgrid", "Vendor", 3, "growth", None, "Email delivery", False),
    ("onfido", "Vendor", 2, "identity", None, "Identity document verification", False),
    # clusters
    ("k8s-prod-a", "Cluster", 1, "data-platform", None, "Primary Kubernetes cluster (ap-south-1a)", False),
    ("k8s-prod-b", "Cluster", 1, "data-platform", None, "Secondary Kubernetes cluster (ap-south-1b)", False),
    ("cdn-edge", "Vendor", 1, "edge-platform", None, "CDN and edge TLS termination", False),
]

# (from, to, mode, protocol). `from` calls `to`.
DEPENDS_ON = [
    ("web-bff", "checkout-api", "sync", "http"),
    ("web-bff", "catalog-service", "sync", "http"),
    ("web-bff", "feature-flags", "sync", "grpc"),
    ("mobile-bff", "search-service", "sync", "http"),
    ("mobile-bff", "catalog-service", "sync", "http"),
    ("mobile-bff", "feature-flags", "sync", "grpc"),
    ("mobile-bff", "notifications-service", "async", "kafka"),
    ("merchant-dashboard", "reporting-service", "sync", "http"),
    ("merchant-dashboard", "catalog-service", "sync", "http"),
    ("checkout-api", "auth-service", "sync", "grpc"),
    ("checkout-api", "payments-core", "sync", "grpc"),
    ("checkout-api", "fraud-service", "sync", "grpc"),
    ("checkout-api", "redis-cache", "sync", "redis"),
    ("checkout-api", "kafka-events", "async", "kafka"),
    ("payouts-api", "auth-service", "sync", "grpc"),
    ("payouts-api", "ledger-service", "sync", "grpc"),
    ("payouts-api", "kyc-service", "sync", "grpc"),
    ("payments-core", "stripe", "sync", "https"),
    ("payments-core", "ledger-service", "sync", "grpc"),
    ("payments-core", "postgres-main", "sync", "sql"),
    ("payments-core", "kafka-events", "async", "kafka"),
    ("ledger-service", "postgres-ledger", "sync", "sql"),
    ("ledger-service", "kafka-events", "async", "kafka"),
    ("refunds-service", "payments-core", "sync", "grpc"),
    ("refunds-service", "ledger-service", "sync", "grpc"),
    ("billing-service", "ledger-service", "sync", "grpc"),
    ("billing-service", "sendgrid", "async", "https"),
    ("auth-service", "user-service", "sync", "grpc"),
    ("auth-service", "session-store", "sync", "redis"),
    ("user-service", "postgres-main", "sync", "sql"),
    ("kyc-service", "onfido", "sync", "https"),
    ("kyc-service", "user-service", "sync", "grpc"),
    ("kyc-service", "sanctions-screening", "sync", "grpc"),
    ("sanctions-screening", "postgres-main", "sync", "sql"),
    ("fraud-service", "risk-scoring", "sync", "grpc"),
    ("fraud-service", "redis-cache", "sync", "redis"),
    ("risk-scoring", "feature-flags", "sync", "grpc"),
    ("risk-scoring", "postgres-main", "sync", "sql"),
    ("search-service", "search-index", "sync", "http"),
    ("search-service", "catalog-service", "sync", "http"),
    ("catalog-service", "postgres-main", "sync", "sql"),
    ("catalog-service", "redis-cache", "sync", "redis"),
    ("notifications-service", "twilio", "sync", "https"),
    ("notifications-service", "sendgrid", "sync", "https"),
    ("notifications-service", "kafka-events", "async", "kafka"),
    ("email-worker", "sendgrid", "sync", "https"),
    ("email-worker", "kafka-events", "async", "kafka"),
    ("reporting-service", "postgres-ledger", "sync", "sql"),
    ("reporting-service", "kafka-events", "async", "kafka"),
]

FAILS_OVER_TO = [("stripe", "adyen")]

# Which component this world faults for each chaos scenario.
SCENARIO_ROOTS = {
    "bad-deploy": "auth-service",
    "vendor-outage": "stripe",
    "flag-regression": "risk-scoring",
    "db-migration-lock": "postgres-ledger",
}

# Hand-written scenario details for the demo world. Worlds without this get generated
# change ids and a decoy picked from the graph at injection time.
SCENARIO_OVERRIDES = {
    "bad-deploy": {
        "title": "Bad deploy on auth-service",
        "change": {"id": "D-4521", "kind": "deploy", "version": "v2.18.0", "author": "priya", "risk": "high",
                   "summary": "Switch token introspection to new connection pool", "minutes_ago": 8},
        "decoy": {"id": "D-4522", "component": "search-service", "kind": "deploy", "version": "v5.1.0",
                  "author": "arjun", "risk": "high", "summary": "New ranking model for search", "minutes_ago": 4},
    },
    "vendor-outage": {
        "title": "Stripe partial outage",
        "decoy": {"id": "C-7710", "component": "notifications-service", "kind": "config", "version": None,
                  "author": "ben", "risk": "medium", "summary": "Raise SMS retry limit", "minutes_ago": 5},
    },
    "flag-regression": {
        "title": "Risk model flag regression",
        "change": {"id": "F-0091", "kind": "flag", "version": "risk.new-model-v3", "author": "ivan", "risk": "high",
                   "summary": "Enable risk model v3 for 100% of traffic", "minutes_ago": 7},
        "decoy": {"id": "D-4530", "component": "reporting-service", "kind": "deploy", "version": "v1.9.0",
                  "author": "kenji", "risk": "medium", "summary": "Faster CSV exports", "minutes_ago": 3},
    },
    "db-migration-lock": {
        "title": "Migration lock on postgres-ledger",
        "change": {"id": "M-0450", "kind": "migration", "version": "m-0450", "author": "maya", "risk": "high",
                   "summary": "Backfill settlement_batch on ledger_entries", "minutes_ago": 9},
        "decoy": {"id": "C-7715", "component": "search-index", "kind": "config", "version": None,
                  "author": "arjun", "risk": "medium", "summary": "Increase index refresh interval", "minutes_ago": 5},
    },
}

# Services run on cluster a, except a few replicated to b.
RUNS_ON_B = {"search-service", "reporting-service", "email-worker", "notifications-service"}

# Baseline metrics per tier: (p95 latency ms, error rate, requests/sec)
BASELINE = {1: (120, 0.002, 800), 2: (180, 0.004, 250), 3: (300, 0.006, 60)}

# --- Business ----------------------------------------------------------------

PRODUCTS = [
    # name, description, entry components
    ("Online Checkout", "Hosted and embedded card checkout", ["web-bff", "checkout-api"]),
    ("Merchant Payouts", "Daily and instant payouts to merchants", ["payouts-api"]),
    ("Merchant Dashboard", "Reports, catalog and settings for merchants", ["merchant-dashboard"]),
    ("Mobile Wallet", "Consumer wallet app", ["mobile-bff"]),
    ("Billing", "Fee invoices for merchants", ["billing-service"]),
]

CUSTOMERS = [
    # id, name, tier, arr_usd, sla_target, {product: gmv_per_hour_usd}
    ("CUST-001", "Acme Retail", "enterprise", 2_400_000, 99.95,
     {"Online Checkout": 42_000, "Merchant Payouts": 9_000, "Merchant Dashboard": 0}),
    ("CUST-002", "Globex Travel", "enterprise", 1_800_000, 99.95,
     {"Online Checkout": 31_000, "Merchant Payouts": 6_500}),
    ("CUST-003", "Initech Foods", "growth", 420_000, 99.9,
     {"Online Checkout": 7_500, "Mobile Wallet": 2_200}),
    ("CUST-004", "Umbrella Health", "enterprise", 1_100_000, 99.95,
     {"Merchant Payouts": 12_000, "Billing": 0, "Merchant Dashboard": 0}),
    ("CUST-005", "Stark Marketplace", "growth", 650_000, 99.9,
     {"Mobile Wallet": 5_400, "Merchant Dashboard": 0}),
]

# --- Company knowledge ---------------------------------------------------------

DECISIONS = [
    {
        "id": "ADR-014", "title": "Checkout calls auth-service synchronously for token introspection",
        "status": "accepted", "days_ago": 410,
        "context": "Checkout needs to verify merchant API tokens and revoked sessions before charging a card. "
                   "Cached JWT validation allowed revoked keys to keep charging for up to 15 minutes.",
        "decision": "checkout-api and payouts-api call auth-service introspection synchronously on every "
                    "money-moving request. No local JWT cache.",
        "consequences": "auth-service is a hard dependency of every payment path. An auth-service regression "
                        "takes checkout and payouts down. Accepted for revocation correctness.",
        "about": ["checkout-api", "payouts-api", "auth-service"],
        "decided_by": ["aisha", "hana"], "threads": ["T-104"],
    },
    {
        "id": "ADR-007", "title": "Stripe as primary acquirer with Adyen failover",
        "status": "accepted", "days_ago": 620,
        "context": "A single acquirer is a single point of failure for card payments.",
        "decision": "payments-core routes to Stripe and fails over to Adyen when Stripe error rate exceeds 5%.",
        "consequences": "Failover is manual-approve to avoid flapping. Adyen fees are 0.1% higher.",
        "about": ["payments-core", "stripe", "adyen"],
        "decided_by": ["diego"], "threads": ["T-102"],
    },
    {
        "id": "ADR-021", "title": "Feature flags evaluated server-side",
        "status": "accepted", "days_ago": 300,
        "context": "Client-side flags leaked unreleased features and made kill switches slow.",
        "decision": "All flags are evaluated by the feature-flags service. Risky flags must have a kill switch.",
        "consequences": "feature-flags is tier 1. Flag changes are recorded as Change events.",
        "about": ["feature-flags", "risk-scoring", "web-bff", "mobile-bff"],
        "decided_by": ["lena", "noor"], "threads": ["T-106"],
    },
    {
        "id": "ADR-009", "title": "Separate ledger database",
        "status": "accepted", "days_ago": 540,
        "context": "Ledger writes competed with catalog and user traffic on postgres-main.",
        "decision": "The ledger lives in postgres-ledger. Schema migrations on it must be online "
                    "(no ACCESS EXCLUSIVE locks) and run off-peak.",
        "consequences": "Two databases to operate. Migration locks on postgres-ledger stall payouts and reporting.",
        "about": ["ledger-service", "postgres-ledger", "reporting-service"],
        "decided_by": ["kenji", "hana"], "threads": ["T-105"],
    },
    {
        "id": "ADR-018", "title": "Kafka for asynchronous event fan-out",
        "status": "accepted", "days_ago": 480,
        "context": "Synchronous webhooks from payments to notifications caused cascading timeouts.",
        "decision": "Domain events are published to kafka-events. Consumers are async and must tolerate lag.",
        "consequences": "Kafka outages cause lag, not errors, for notification and reporting paths.",
        "about": ["kafka-events", "notifications-service", "reporting-service", "email-worker"],
        "decided_by": ["omar", "kenji"], "threads": ["T-107"],
    },
]

RUNBOOKS = [
    {
        "id": "RB-001", "reviewed_days_ago": 130, "title": "Roll back an auth-service deploy",
        "body": "1. Confirm error spike on checkout-api and payouts-api introspection calls. "
                "2. `deployctl rollback auth-service --to previous`. 3. Watch auth p95 return under 150ms. "
                "4. Flush session-store only if token format changed.",
        "covers": ["auth-service", "session-store"], "wrote": "priya",
    },
    {
        "id": "RB-002", "reviewed_days_ago": 20, "title": "Fail over card processing from Stripe to Adyen",
        "body": "1. Check Stripe status page and payments-core acquirer error rate. "
                "2. `payctl acquirer set-primary adyen`. 3. Verify authorisation rate recovers. "
                "4. Fail back after Stripe is green for 30 minutes.",
        "covers": ["payments-core", "stripe", "adyen"], "wrote": "hana",
    },
    {
        "id": "RB-003", "reviewed_days_ago": 5, "title": "Kill a risky feature flag",
        "body": "1. Identify the flag from recent Change events on the affected service. "
                "2. `flags off <flag> --env prod`. 3. Confirm risk-scoring errors drop.",
        "covers": ["feature-flags", "risk-scoring"], "wrote": "ivan",
    },
    {
        "id": "RB-004", "reviewed_days_ago": 25, "title": "Clear a blocking migration lock on Postgres",
        "body": "1. `SELECT * FROM pg_locks WHERE granted = false`. 2. Identify the migration session. "
                "3. Cancel it with pg_cancel_backend and roll the migration back. 4. Re-run online.",
        "covers": ["postgres-ledger", "postgres-main"], "wrote": "maya",
    },
    {
        "id": "RB-005", "reviewed_days_ago": 15, "title": "Recover from Kafka consumer lag",
        "body": "1. Check consumer group lag per partition. 2. Scale the lagging consumer. "
                "3. If brokers are unhealthy, page data-platform on-call.",
        "covers": ["kafka-events"], "wrote": "omar",
    },
]

THREADS = [
    {"id": "T-101", "channel": "#incidents", "days_ago": 120, "author": "priya",
     "title": "INC-2093 auth-service token cache regression",
     "body": "Rolled back auth-service v2.14.0. The new token cache returned stale introspection results "
             "under load, so checkout and payouts rejected valid tokens.",
     "mentions": ["auth-service", "checkout-api", "payouts-api"]},
    {"id": "T-102", "channel": "#team-payments", "days_ago": 620, "author": "diego",
     "title": "Do we need a second acquirer?",
     "body": "Stripe had two partial outages this quarter. Proposing Adyen as a failover acquirer.",
     "mentions": ["stripe", "adyen", "payments-core"]},
    {"id": "T-103", "channel": "#team-growth", "days_ago": 40, "author": "arjun",
     "title": "Search reindex plan",
     "body": "Reindex will run nightly in batches to avoid the overload we saw in INC-2156.",
     "mentions": ["search-service", "search-index"]},
    {"id": "T-104", "channel": "#architecture", "days_ago": 412, "author": "hana",
     "title": "Why checkout calls auth synchronously",
     "body": "We had revoked merchant keys still charging cards for 15 minutes because of cached JWTs. "
             "Aisha and I agreed checkout should introspect every token against auth-service synchronously. "
             "Trade-off: auth becomes a hard dependency of checkout and payouts.",
     "mentions": ["checkout-api", "auth-service", "payouts-api"]},
    {"id": "T-105", "channel": "#team-data", "days_ago": 545, "author": "kenji",
     "title": "Moving the ledger off postgres-main",
     "body": "Ledger write latency spikes during catalog imports. Plan is a dedicated postgres-ledger.",
     "mentions": ["postgres-ledger", "postgres-main", "ledger-service"]},
    {"id": "T-106", "channel": "#architecture", "days_ago": 302, "author": "lena",
     "title": "Server-side flags and kill switches",
     "body": "Every risky flag needs a kill switch in feature-flags. Noor wants this for model rollouts.",
     "mentions": ["feature-flags", "risk-scoring"]},
    {"id": "T-107", "channel": "#architecture", "days_ago": 482, "author": "omar",
     "title": "Kafka for notifications",
     "body": "Webhooks from payments to notifications keep timing out. Moving to kafka-events fan-out.",
     "mentions": ["kafka-events", "notifications-service"]},
    {"id": "T-108", "channel": "#incidents", "days_ago": 30, "author": "maya",
     "title": "INC-2178 users table migration lock",
     "body": "ALTER TABLE on users took an ACCESS EXCLUSIVE lock. Rolled back and re-ran with a concurrent index.",
     "mentions": ["postgres-main", "user-service"]},
]

# Base expertise scores, before the Scribe starts learning.
EXPERT_IN = [
    ("priya", "auth-service", 0.9), ("marcus", "session-store", 0.7), ("aisha", "auth-service", 0.6),
    ("hana", "payments-core", 0.9), ("hana", "checkout-api", 0.8), ("tom", "payouts-api", 0.7),
    ("maya", "postgres-ledger", 0.9), ("maya", "postgres-main", 0.8), ("omar", "kafka-events", 0.9),
    ("ivan", "risk-scoring", 0.9), ("ravi", "web-bff", 0.8), ("sofia", "feature-flags", 0.7),
    ("ben", "catalog-service", 0.7), ("arjun", "search-service", 0.6), ("zara", "fraud-service", 0.7),
]

# --- Incident history (episodic memory) -------------------------------------------

# root: ("change", component, kind, version, summary, author) or ("component", component)
INCIDENTS = [
    {"id": "INC-2093", "days_ago": 120, "severity": "SEV1",
     "title": "Checkout and payouts rejecting valid tokens",
     "summary": "auth-service v2.14.0 shipped a token cache that returned stale introspection results. "
                "Checkout and payouts failed auth for 40% of requests. Rolled back in 6 minutes.",
     "root": ("change", "auth-service", "deploy", "v2.14.0", "Add introspection token cache", "priya"),
     "affected": ["auth-service", "checkout-api", "payouts-api", "web-bff"],
     "responders": ["priya", "marcus"], "action": "rollback", "ttm_min": 6},
    {"id": "INC-2101", "days_ago": 110, "severity": "SEV1",
     "title": "Card authorisations failing at Stripe",
     "summary": "Stripe returned elevated 5xx. Failed over to Adyen per ADR-007.",
     "root": ("component", "stripe"),
     "affected": ["stripe", "payments-core", "checkout-api", "web-bff"],
     "responders": ["hana", "diego"], "action": "failover", "ttm_min": 14},
    {"id": "INC-2110", "days_ago": 96, "severity": "SEV2",
     "title": "Payouts stalled by ledger migration lock",
     "summary": "Migration adding a column to ledger_entries took an exclusive lock. Rolled back.",
     "root": ("change", "postgres-ledger", "migration", "m-0412", "Add settlement_batch to ledger_entries", "maya"),
     "affected": ["postgres-ledger", "ledger-service", "payouts-api", "reporting-service"],
     "responders": ["maya", "kenji"], "action": "rollback", "ttm_min": 22},
    {"id": "INC-2117", "days_ago": 88, "severity": "SEV2",
     "title": "Checkout fraud checks timing out",
     "summary": "Flag risk.new-model-v2 enabled a model that exceeded the latency budget. Flag turned off.",
     "root": ("change", "risk-scoring", "flag", "risk.new-model-v2", "Enable risk model v2 for 100%", "ivan"),
     "affected": ["risk-scoring", "fraud-service", "checkout-api", "web-bff"],
     "responders": ["ivan", "noor"], "action": "flag_off", "ttm_min": 9},
    {"id": "INC-2124", "days_ago": 80, "severity": "SEV3",
     "title": "Notification delays",
     "summary": "Consumer lag on kafka-events after a partition rebalance. Scaled consumers.",
     "root": ("component", "kafka-events"),
     "affected": ["kafka-events", "notifications-service"],
     "responders": ["omar"], "action": "scale", "ttm_min": 35},
    {"id": "INC-2131", "days_ago": 72, "severity": "SEV3",
     "title": "Email receipts not sending",
     "summary": "SendGrid outage. Waited for vendor recovery.",
     "root": ("component", "sendgrid"),
     "affected": ["sendgrid", "email-worker", "notifications-service"],
     "responders": ["ben"], "action": "page", "ttm_min": 60},
    {"id": "INC-2138", "days_ago": 64, "severity": "SEV2",
     "title": "Product pages failing to load",
     "summary": "catalog-service v4.2.0 had an N+1 query against postgres-main. Rolled back.",
     "root": ("change", "catalog-service", "deploy", "v4.2.0", "Inline variant pricing", "ben"),
     "affected": ["catalog-service", "web-bff", "mobile-bff", "merchant-dashboard"],
     "responders": ["chloe", "ben"], "action": "rollback", "ttm_min": 18},
    {"id": "INC-2142", "days_ago": 58, "severity": "SEV2",
     "title": "Cache eviction storm",
     "summary": "maxmemory-policy changed to allkeys-random caused hot keys to drop. Config reverted.",
     "root": ("change", "redis-cache", "config", "cfg-77", "Change maxmemory-policy", "omar"),
     "affected": ["redis-cache", "checkout-api", "catalog-service"],
     "responders": ["omar", "sofia"], "action": "rollback", "ttm_min": 12},
    {"id": "INC-2150", "days_ago": 50, "severity": "SEV2",
     "title": "Login failures from session-store connection exhaustion",
     "summary": "Pool size config on auth-service exhausted session-store connections. Reverted config.",
     "root": ("change", "auth-service", "config", "cfg-81", "Raise session pool size to 512", "marcus"),
     "affected": ["auth-service", "session-store", "checkout-api"],
     "responders": ["marcus", "priya"], "action": "rollback", "ttm_min": 11},
    {"id": "INC-2156", "days_ago": 42, "severity": "SEV3",
     "title": "Search latency spike",
     "summary": "Full reindex overloaded search-index. Paused reindex.",
     "root": ("change", "search-index", "config", "cfg-90", "Start full reindex", "arjun"),
     "affected": ["search-index", "search-service", "mobile-bff"],
     "responders": ["arjun", "ben"], "action": "rollback", "ttm_min": 25},
    {"id": "INC-2161", "days_ago": 35, "severity": "SEV3",
     "title": "KYC checks slow",
     "summary": "Onfido latency degraded. Paged vendor and waited.",
     "root": ("component", "onfido"),
     "affected": ["onfido", "kyc-service", "payouts-api"],
     "responders": ["zara"], "action": "page", "ttm_min": 48},
    {"id": "INC-2167", "days_ago": 31, "severity": "SEV2",
     "title": "Web checkout blank page",
     "summary": "web-bff v7.3.1 broke the bundle manifest. Rolled back.",
     "root": ("change", "web-bff", "deploy", "v7.3.1", "Upgrade bundler", "ravi"),
     "affected": ["web-bff"],
     "responders": ["ravi", "lena"], "action": "rollback", "ttm_min": 8},
    {"id": "INC-2172", "days_ago": 24, "severity": "SEV1",
     "title": "Duplicate charges on retry",
     "summary": "payments-core v3.9.0 dropped the idempotency key on retries. Rolled back and refunded.",
     "root": ("change", "payments-core", "deploy", "v3.9.0", "Refactor acquirer retry loop", "tom"),
     "affected": ["payments-core", "checkout-api", "web-bff", "refunds-service"],
     "responders": ["tom", "hana", "diego"], "action": "rollback", "ttm_min": 16},
    {"id": "INC-2178", "days_ago": 30, "severity": "SEV2",
     "title": "User lookups blocked by migration",
     "summary": "ALTER TABLE on users took an ACCESS EXCLUSIVE lock. Rolled back.",
     "root": ("change", "postgres-main", "migration", "m-0433", "Add index on users.email", "maya"),
     "affected": ["postgres-main", "user-service", "auth-service", "checkout-api"],
     "responders": ["maya"], "action": "rollback", "ttm_min": 14},
    {"id": "INC-2185", "days_ago": 12, "severity": "SEV2",
     "title": "Feature flag service crash loop",
     "summary": "feature-flags pods OOM-killed after config reload. Restarted with higher memory limit.",
     "root": ("component", "feature-flags"),
     "affected": ["feature-flags", "web-bff", "mobile-bff", "risk-scoring"],
     "responders": ["sofia"], "action": "restart", "ttm_min": 10},
]

# Routine background changes (not incident causes). Generated deterministically in seed.py.
BACKGROUND_CHANGE_COUNT = 66
CHANGE_KINDS = ["deploy", "deploy", "deploy", "config", "flag", "migration"]
