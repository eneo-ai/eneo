# Sitemap crawl webhooks

Apply the Alembic migration (`alembic upgrade head`) before deploying the API
and workers, then deploy the frontend with its updated SDK. Existing websites
retain their current schedules. Rollback must downgrade the migration before
running old application code; downgrade changes `webhook` schedules to `never`.

Select **Webhook** under automatic updates for a sitemap website, save it, and
select **Create token**. Copy the POST example before closing the editor. Only
the SHA-256 hash is stored; a lost token must be rotated. Rotation immediately
invalidates the previous token. Keep the token on the calling server, never in
browser JavaScript or source control.

```sh
curl --request POST 'https://eneo.example/api/v1/webhooks/websites/WEBSITE_ID/crawl' \
  --header "Authorization: Bearer $CRAWL_WEBHOOK_TOKEN"
```

The body is optional and does not change crawl parameters. A `202` response
means the request is committed to the database. `queued` means a crawl is
scheduled, `pending` means it waits for the current run or backoff, and
`coalesced` means an existing queued/requested run covers the request. Requests
before execution starts are combined. Requests during execution schedule at most
one following run. Internal task retries do not consume that following request.
The initial crawl on website creation and manual starts remain available.

Production requires HTTPS. Configure the reverse proxy and ASGI server to trust
forwarded scheme/host information only from the deployment's own proxy, so the
backend sees the external HTTPS scheme and generates the correct webhook URL.
Do not log Authorization headers. No CORS/origin setting is needed for a
server-to-server caller.

`CRAWL_WEBHOOK_RATE_LIMIT_PER_MINUTE` defaults to 60 authenticated requests per
crawler. `429` includes `Retry-After`; retry `503` after a delay. Invalid, revoked,
and wrong-crawler tokens return `401`. If the rate limiter is unavailable, the
request is rejected before it is accepted.

Workers recover committed requests every 10 seconds using the Python crawler's
durable attempts and dispatcher. Normal concurrency limits and failure backoff apply. After ten
consecutive crawl failures automatic updates stop and the token is revoked.
Select webhook again and issue a new token to resume. Switching away from webhook
cancels unstarted webhook runs and revokes the token; it does not interrupt a
running crawl. Pending requests and dispatch records survive process restarts.

Monitor `Crawl webhook accepted`, `Crawl webhook token rotated`,
`Webhook dispatch failed`, and `Webhook reconciliation failed` log events.
Persistent dispatch failures require checking worker, database and Redis health.
