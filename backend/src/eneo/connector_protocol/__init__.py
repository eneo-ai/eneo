"""Eneo as a connector: the connector protocol (version 3) served by Eneo.

A system that speaks the protocol (a start page for staff, say) registers
Eneo's address and a shared key, and from then on lists the assistants a person
may ask from outside Eneo and hands their questions over. Every call carries
two credentials: the calling installation's own (a shared key and a signed
assertion bound to the request) and the person's (an access token from the
shared identity provider, issued for Eneo). The first says which installation
is calling; the second alone decides what the person may see and ask.

The surface is absent until a tenant administrator trusts an installation.
"""
