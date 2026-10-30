"""The only way flow code reaches a network destination a flow author chose.

Contract for every transport that lives here (http today; sftp, ftp or smtp
would follow the same rules):

* A transport never resolves a name itself. It asks ``vet_destination`` for the
  addresses the policy allows and connects to one of those IP literals, so the
  address that was checked is the address that is used.
* Nothing is sent before the connection to a vetted address exists.
* Follow-up connections are destinations too. An FTP passive data channel must
  reuse the control connection's address, not the one the server announces; SMTP
  must vet every MX address it resolves; a redirect or referral is a new
  destination to vet, or it is not followed.
* One monotonic deadline covers name resolution and every TCP connection attempt
  (not the TLS handshake or the response, which httpx times separately), and
  resolution runs on the bounded pool in ``resolver`` so stalled names cannot
  starve the process. Attempts alternate address families.

``tests/unittests/flows/test_flow_egress_boundary.py`` fails when flow code
reaches a known network sink outside this package; its docstring states the limits.
"""
