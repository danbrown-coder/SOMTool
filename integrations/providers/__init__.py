"""Third-party integration provider adapters.

Each sub-module registers its `ProviderSpec` with the integrations registry
via `integrations.register_provider(...)` at import time. A shared webhook
dispatcher (`integrations.webhooks`) routes inbound `/webhooks/<provider>`
traffic into per-provider handlers that each adapter registers alongside its
spec.

Design goals:
  - One file per provider for fast navigation and small diffs.
  - Lazy-import third-party SDKs so a missing optional dep never crashes.
  - Uniform "ProviderSpec + Client + register_webhook" shape.
"""
