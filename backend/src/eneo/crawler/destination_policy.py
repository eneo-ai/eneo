"""Destination policy for the website crawler.

The crawler may connect to public and private (intranet) unicast addresses,
but never to loopback, link-local, unspecified, multicast, IPv4-in-IPv6
transition addresses or the known cloud metadata endpoints. Operators who do
not crawl intranet sites can set CRAWLER_BLOCK_PRIVATE_NETWORKS to also refuse
private ranges.

The Python crawler enforces the policy in its name resolver, so it applies to
the addresses a connection actually uses: start URLs, redirects, followed
links, sitemap entries, robots.txt and file downloads. A DNS answer is used
only when every address in it is allowed.

The address classification itself is ``eneo.main.destination_policy``, kept apart
from the crawler so the flows egress can build its own accepted set from the same
primitives; the crawler imports the policy from here.
"""

from __future__ import annotations

from eneo.main.destination_policy import DestinationPolicy

__all__ = ["DestinationPolicy"]
