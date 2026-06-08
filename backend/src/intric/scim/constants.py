"""SCIM 2.0 server limits advertised in /ServiceProviderConfig and enforced
by the corresponding endpoints.

The values are aligned with the conservative side of common SCIM server
defaults across the industry (Azure Entra ID, Okta, Ping, Microsoft Identity
Manager). They balance two competing concerns:

- Large enough to be useful: 100 ops / 1 MiB matches Entra's default chunking
  and Okta's published bulk recommendations, so well-behaved IdPs rarely have
  to split a sync into more requests than necessary.
- Small enough to bound resource use: a single bulk fits comfortably within
  one DB transaction and one worker without risking long-running locks or
  large memory spikes on the application server.

Per RFC 7644 §3.7.3, requests exceeding either limit return HTTP 413.
"""

SCIM_BULK_MAX_OPERATIONS = 100
SCIM_BULK_MAX_PAYLOAD_BYTES = 1024 * 1024  # 1 MiB
SCIM_FILTER_MAX_RESULTS = 200
