# Durable object content

The primary, navigable operator guide is [Choose Content
Storage](https://docs.eneo.ai/guides/object-content-storage). This file is the
offline reference shipped beside the Compose templates.

## TL;DR

- Eneo runs normally without S3-compatible storage. PostgreSQL inline is the
  complete ready-to-use default.
- Administrators connect an S3-compatible destination and choose the
  deployment-wide target for eligible new File and Icon writes in **Admin >
  Storage**. These changes need no backend or worker restart.
- PostgreSQL owns identity, SHA-256, size/type, references, access, retention,
  and lifecycle. Exactly one selected backend owns each payload.
- Compatible object storage is optional. Enabling or selecting it never moves
  existing bytes; migration is always explicit and verified.
- Eneo never falls back, dual-writes, or creates provider-specific product
  modes.
- Use the docs-site guide above to choose and configure a path. Continue here
  only for the full offline operations and recovery reference.

Eneo keeps one common content identity and lifecycle in PostgreSQL. Each content
record then names exactly one byte authority:

- `postgres_inline` stores bounded bytes in a one-to-one PostgreSQL row;
- `object_store` stores bytes behind one private S3-compatible endpoint.

PostgreSQL always owns the typed content identity, media type, canonical
SHA-256, exact size, authorization references, holds, retention, lifecycle
state, audit, and reconciliation facts. The chosen byte backend owns only the
payload. Selection is explicit when content is created and never changes
silently after a failure.

| Owner         | Responsibility                                                                                                                                                                     |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Administrator | Connect an S3-compatible destination, change or roll back that destination, rotate its access keys, and set the new-write target and business upload limits in **Admin > Storage** |
| Operator      | Run PostgreSQL and any optional compatible endpoint; own TLS, certificates, capacity, backups, network reachability, and process safety tuning                                     |

Storage administration uses the same administrator authority as API keys and
models. Deployment-wide content inventory spans tenants, so it is part of that
same administrative view. **Admin > Storage** leads with the active target,
object-store health, recorded file-content distribution, and migration state.
Changing the target, editing upload limits, and moving existing content remain
separate actions; detailed limits and PostgreSQL allocation stay available in
expandable technical details.

Persisted business limits accept whole-byte values from 1 through
9,007,199,254,740,991 so PostgreSQL and browser clients can round-trip the same
integer exactly. This representation bound is not a business default or a
capacity recommendation; the applicable operator ceiling can still make the
effective limit lower.

The default deployment uses PostgreSQL-inline storage and does not start
SeaweedFS or require S3-compatible configuration. Operators can enable the
bundled profile or connect an external endpoint when object size, capacity, or
availability requirements justify it. There is no production filesystem
backend, automatic fallback, dual write, public object URL, provider registry,
or provider-specific product branch.

File and Icon are the first adopted product owners. Existing legacy bytes stay
readable while a staged, resumable backfill creates and verifies concrete typed
references. The old columns remain the recovery source until a later contract
release confirms that no legacy item remains. Eligible new File and Icon writes
use the target selected in **Admin > Storage**. InfoBlob generations and Flow
artifacts remain separate follow-up work. A target change affects new writes
only; moving existing content remains a separate migration workflow.

## Choose the endpoint

For a new installation, the operator sets Eneo's root encryption key. A platform
admin can then enter the endpoint, bucket, signing region, and access keys in
**Admin > Storage**. Eneo tests the destination before encrypting and saving the
credentials. Saving the connection does not select it for new writes or move
existing content.

An administrator chooses the destination, as they do for AI provider and
MCP server endpoints. Restrict which hosts the backend may reach with your normal
network controls if your deployment requires that boundary.

Earlier releases required operators to approve endpoint origins through
`OBJECT_CONTENT_ADMIN_ALLOWED_ENDPOINT_ORIGINS`. That setting is gone. A leftover
value is ignored rather than rejected, so remove it from your deployment
configuration whenever convenient.

Existing operator-managed connections supplied through `OBJECT_CONTENT_*`
remain supported as trusted deployment input. When encrypted persistence is
available, Eneo adopts that connection without changing its destination;
otherwise it remains read-only in the admin interface. Do not configure the
same destination through both paths.

The optional `object-content` Compose profile starts an Eneo-built SeaweedFS
4.40 service on the private `object_content_net`. The image is built from upstream commit
`875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa`, not from an upstream image. Eneo
pins the source archive, build image, runtime image, and GitHub Actions; scans
the exact amd64 and arm64 image digests; publishes CycloneDX 1.6 and SPDX SBOMs;
and signs provenance and SBOM attestations with Eneo's GitHub Actions identity.
The source evidence also records a hashed downstream patch that upgrades gRPC
to 1.82.1 until an upstream SeaweedFS release contains the fix.
This proves what Eneo built. It is not supplier-signed SeaweedFS provenance.

An operator may instead use a self-hosted or European-operated S3-compatible
endpoint. MinIO is supported this way: it is neither bundled nor special-cased.
No Amazon service is required or selected implicitly. Every external endpoint
must pass the same tested subset:

- SigV4 authentication and path or virtual-host addressing;
- bucket-scoped paginated object and multipart listing;
- single-part `PUT`, `HEAD`, streaming `GET`, and one byte range;
- multipart create, ordered part upload, complete, abort, and list;
- object deletion with observable not-found convergence.

Eneo does not require AWS additional-checksum extensions from an external
endpoint. Some compatible services implement them fully, some omit them, and
some accept only the core multipart fields.

Native range support is an endpoint conformance gate. Eneo fetches and verifies
only the persisted upload chunks covering the requested interval before sending
response headers. Content migrated as one whole-object chunk retains its
full-verification cost for range reads.

Eneo computes the canonical full-byte SHA-256 incrementally over its own upload
stream and stores it in PostgreSQL. Every new remote write is streamed back and
rehashed before it becomes available. S3 ETags, multipart composite checksums,
CRCs, and user metadata never replace that digest. The same read-back contract
also applies to a bypassing upload, migration, restore, or ambiguous
reconciliation.

For an external endpoint, set `OBJECT_CONTENT_ENDPOINT_URL`, TLS, addressing,
signing region, bucket, credentials, and the stable deployment ID in `.env`,
then start the normal stack:

```bash
docker compose up -d
```

Do not enable the `object-content` profile. Eneo connects only to the explicit
external endpoint.

Do not route either endpoint through the public reverse proxy. Give Eneo access
to one dedicated bucket; do not use bucket-per-tenant or cross-deployment
deduplication. Keep versioning and Object Lock disabled for the active content
bucket: the current deletion contract removes one opaque key and does not claim
to purge retained historical versions. Use paired storage snapshots/backups for
recovery instead.

### External MinIO example

Eneo does not bundle, license, or administer MinIO. Deploy MinIO in the region
and topology your organization requires, using MinIO's current production and
licensing guidance. Expose its S3 API to the Eneo backend and worker over a
private route; do not expose its administrative console through Eneo.

Create one private bucket for this Eneo deployment:

```bash
mc mb eneo-minio/eneo-object-content
```

Create a non-admin application identity and restrict it to that bucket. The
following policy is the minimum permission set used by the current Eneo
adapter; save it as `eneo-object-content-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:ListBucketMultipartUploads"],
      "Resource": ["arn:aws:s3:::eneo-object-content"]
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts"
      ],
      "Resource": ["arn:aws:s3:::eneo-object-content/*"]
    }
  ]
}
```

MinIO uses IAM-compatible `arn:aws:s3` resource syntax in local policy files.
Those identifiers do not connect Eneo or MinIO to an Amazon service. If you
change `OBJECT_CONTENT_BUCKET`, change both policy resources to match.

Create the service identity through your MinIO console, identity provider, or
secret-safe automation, then attach the policy. Do not pass a secret key on a
command line:

```bash
mc admin policy create eneo-minio eneo-object-content \
  ./eneo-object-content-policy.json
mc admin policy attach eneo-minio eneo-object-content \
  --user '<service-identity>'
```

Put the generated application credentials in the protected deployment `.env`
or your Compose secret injection, then configure:

```dotenv
OBJECT_CONTENT_ENDPOINT_URL=https://minio.storage.example.eu:9000
OBJECT_CONTENT_REGION=<the signing scope configured by the MinIO operator>
OBJECT_CONTENT_BUCKET=eneo-object-content
OBJECT_CONTENT_ACCESS_KEY_ID=<application access key>
OBJECT_CONTENT_SECRET_ACCESS_KEY=<application secret key>
OBJECT_CONTENT_ALLOW_INSECURE_HTTP=false
```

Keep `OBJECT_CONTENT_ADDRESSING_STYLE=path` unless the MinIO operator has
configured virtual-host buckets and matching wildcard DNS/TLS. For a private
CA, mount its certificate read-only into both backend and worker and set
`OBJECT_CONTENT_CA_BUNDLE` in `env_backend.env` to the in-container path.

Start Eneo without the bundled profile, then verify readiness:

```bash
docker compose up -d
curl -fsS https://eneo.example.eu/api/readyz \
  | jq -e '.detail.object_content.code == "ready"'
```

After readiness reports `ready`, an administrator can select **Object store**
in **Admin > Storage**. Selection fails clearly if the endpoint is unavailable
or incompatible. The policy update takes effect without restarting backend or
worker.

HTTP 200 alone can also represent degraded remote storage while inline content
remains available, so deployment checks must verify the explicit code.

Before production traffic, validate a staging Eneo deployment against the exact
MinIO version and configuration you will operate. Exercise single and multipart
upload (including ordered part listing), full and range read, delete visibility,
bucket isolation, TLS trust, and paired restore; Eneo's object-content
integration suite defines those expected behaviors. Keep versioning, Object
Lock, and object-store lifecycle retention disabled for the active-content
bucket. Use paired storage snapshots/backups for recovery; an object-store rule
must not silently keep purged content longer than approved.

## Configuration states

The default Compose installation leaves every remote-only setting absent.
Backend and worker start the common module, serve PostgreSQL-inline content,
and report `object_content.code=object_store_not_configured`. Local lifecycle,
reference audit, retention, and deletion reconciliation continue to run.

To enable bundled SeaweedFS, copy `.env.template`, set mode `0600`, uncomment
the complete object-store block, and pin `ENEO_SEAWEEDFS_IMAGE` to the exact
manifest digest in the release's `IMAGE-DIGESTS.txt`. Then run:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.object-content.yml \
  --profile object-content up -d
```

The backend and worker receive the same variables through Compose pass-through;
the optional service receives the matching credentials. There is deliberately
no usable mutable-tag default.

When readiness reports `ready`, an administrator can select **Object store** in
**Admin > Storage**. The same deployment-wide policy applies to bundled and
external endpoints; there is no provider or vendor product branch.

Remote-only settings are all-or-nothing. Do not model “off” with blank values:
leave every remote-only variable absent. Core settings such as
`OBJECT_CONTENT_INLINE_MAXIMUM_BYTES` and reconciliation bounds are valid
without an endpoint. Any remote endpoint, credential, transport, multipart, or
object-inventory value activates strict object-store validation.

If active `object_store` rows exist, removing the endpoint configuration fails
closed with `configuration_required`. Inline rows remain healthy without a
remote endpoint. Eneo never moves an individual record from one backend to the
other as an outage fallback.

`OBJECT_CONTENT_DEPLOYMENT_ID` is generated once with `uuidgen`. It scopes
opaque keys and must survive upgrades and paired restores. Changing it does not
migrate data: existing PostgreSQL rows then point outside the active namespace
and reads fail closed. Never rotate it during an ordinary upgrade. A change
requires an explicit, verified content migration and paired recovery plan.

`OBJECT_CONTENT_REGION` is the SigV4 signing region. It does not move or label
the bundled volume: that data stays wherever the operator mounts it. The
bundled SeaweedFS endpoint uses the neutral `local` signing scope. For an
external endpoint, use the value required by its operator. The endpoint URL is
always explicit, so the application never discovers or falls back to an Amazon
service.

Use `OBJECT_CONTENT_ALLOW_INSECURE_HTTP=true` only for the bundled endpoint on
the private Compose network. External endpoints should use HTTPS. Mount an
external private CA read-only into both backend and worker, then set
`OBJECT_CONTENT_CA_BUNDLE` in `env_backend.env`. Do not put credentials in the
endpoint URL, command line, image, repository, logs, or backup manifest.

Inline capacity and common reconciliation tuning live in `env_backend.env`.
`OBJECT_CONTENT_INLINE_MAXIMUM_BYTES` is an operator admission ceiling that
bounds PostgreSQL row, WAL, backup, and process memory exposure; it is not a
business limit. Lowering it affects new inline writes, not reads of existing
rows. For PostgreSQL-inline session uploads, the effective limit is the smaller
of the admin policy and this ceiling. **Admin > Storage** shows the configured
limit, effective limit, and constraining source. Object-store session uploads
use the same rule with the portable multipart envelope derived from configured
transport settings. FastAPI/Starlette multipart parsing happens before route
admission and may use temporary disk. Eneo rejects an oversized File or Icon
before its own capture/spool or any storage mutation. Operators must use
ingress/request-body limits and configure and monitor temporary-disk capacity
to protect that earlier parsing boundary.

Business limits apply to the user's original upload. Generated text, model
input, and page variants may be larger and are bounded by the selected
backend's operator ceiling instead of a second business limit.

Object-store transport, bounded-memory spool, multipart, deletion, and orphan
tuning is optional and should remain commented out until the endpoint is
enabled. These are deployment controls, not tenant policy.
`OBJECT_CONTENT_BINDING_CLAIM_SECONDS` bounds first-start coordination and must
cover the configured readiness request window; increase it only when a measured
endpoint requires longer readiness timeouts. This is liveness tuning that avoids
premature claim takeover and retry; the durable creation-intent state, not the
timeout value, prevents a second store from being paired. Rejected configuration
diagnostics name the invalid field and reason without rendering the supplied
value, so a mistaken credential-bearing endpoint is not copied into startup
logs.

## Runtime and health

Object content has these explicit runtime outcomes:

| Deployment state                                          | Process                              | Readiness / operations                                                                                       |
| --------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Remote settings absent; no active object-store rows       | Starts inline-capable                | Healthy `object_store_not_configured`; local work continues                                                  |
| Remote settings absent; active object-store rows exist    | Starts fail-closed                   | `configuration_required`; remote content is not stranded silently                                            |
| Any blank, partial, or invalid remote settings            | Startup fails                        | Clear configuration validation error                                                                         |
| Complete settings; PostgreSQL and endpoint available      | Starts inline + object-store capable | Healthy `ready`                                                                                              |
| Complete settings; endpoint temporarily unavailable       | Stays live                           | Overall readiness remains 200/degraded; object-store operations return typed 503, inline operations continue |
| Reachable bucket not paired with this PostgreSQL database | Startup fails                        | `configuration_required`; reconciliation does not mutate rows or objects                                     |

Selecting **Object store** in **Admin > Storage** fails clearly while the
endpoint is unavailable or incompatible; the previous committed policy remains
active. If the endpoint fails after selection, eligible new remote-target writes
fail. Eneo does not fall back to PostgreSQL inline or dual-write. Existing remote
content remains unavailable until the configured endpoint recovers.

If the admin's save request loses its response, the commit outcome is unknown:
the browser keeps the submitted draft but blocks another save until the admin
reloads the current persisted revision. Do not infer the active target from the
failed request alone.

Each API and worker process evaluates its deployment environment independently,
so supply the same settings to all of them. Process liveness and core readiness
do not depend on an optional endpoint. Health output includes only a status and
stable code, never endpoint, bucket, key, credentials, or provider details.
Each process coalesces concurrent object-store probes and caches the latest
result for at most one second. This protects PostgreSQL and the endpoint from
probe bursts; an outage or recovery may therefore take up to one second to
appear. `/api/livez` remains dependency-free and uncached.

The first enabled startup creates one random database identity in PostgreSQL.
PostgreSQL grants one process a bounded bootstrap claim; other API or worker
processes remain unready while that claim is active. The claim owner first
checks for an existing marker, durably records marker-creation intent, creates
the marker with a conditional non-overwriting write, and only then confirms the
pair in PostgreSQL. Later startups, readiness probes, and every reconciliation
run require that exact pair. A missing or different marker is never adopted or
overwritten after confirmation. This prevents two concurrently misconfigured
processes from pairing one database with different stores.

An expired claim is reclaimable. A process that crashed before marker creation
was recorded can be retried; a process that wrote the marker before crashing is
recovered by verifying that marker. If PostgreSQL records that creation began
but the configured store has no marker, the outcome is ambiguous and readiness
fails with `configuration_required`. Do not create a marker in another bucket.
Keep writers and reconciliation stopped, inspect every previously configured
store and the paired backup record, then recover the matching pair. The marker
is an internal safety invariant, not an administrator or tenant setting, and
must be included in bucket backups.

Remote mutations are fenced by durable PostgreSQL intent or a bounded
publication reservation before remote work. Bounded leases, idempotency,
retries, multipart abort records, tombstones, and two-sided reconciliation
converge after a process or network failure. Delete intent is irreversible. A
final reference cannot delete content while a hold or minimum-retention
boundary blocks it.

A new inline record commits its verified payload, immediately available control
row, and exactly one first File, InfoBlob, or Icon reference in the same
transaction. For eligible new File and Icon object-store writes, Eneo first
uploads and HEAD verifies every captured payload under opaque reserved keys.
One short transaction then creates already-`available` control and descriptor
rows, product metadata, and exactly one concrete reference per payload. A crash
before that transaction leaves no invisible File or Icon; only row-less remote
bytes remain, and the existing repeated-inventory grace path removes them.
Deferred PostgreSQL constraints reject an ownerless record, a mismatched
backend, or multiple first references.

Hard deletion is also fenced in PostgreSQL. Active holds cannot be removed with
a direct row delete, and retained content cannot bypass the lifecycle. A
`tombstoned` row is purgeable only after the database-owned
`tombstone_purge_after` horizon is present and has elapsed. A missing horizon
means “retain the tombstone”; it is never interpreted as immediate permission
to purge. User account erasure clears hold attribution through its foreign key
without releasing the hold or changing content state.

Object-content reconciliation is a queue-neutral async task. The current worker
registers and schedules it with ARQ; the lifecycle implementation does not
import ARQ. Replacing ARQ with another worker implementation therefore changes
the scheduling/registration adapter, not S3 or lifecycle logic.

### Move existing content

PostgreSQL inline remains a complete deployment without an object-store
service or configuration. When compatible object storage is configured and
ready, an administrator can use **Admin > Storage** to queue an explicit
move in either direction. Selecting the default target for new writes never
moves existing content.

Each queue command inspects 1–100 eligible items in creation order and persists
one resumable intent per content item. The worker processes at most one move per
reconciliation run. **Pause moves** blocks new claims; an item that already
holds a claim may finish its verified authority flip. The progress table groups
item and byte counts by destination, state, and typed failure reason. Run
another bounded command to queue the next page; Eneo does not run a scheduled
or automatic fleet migration.

For PostgreSQL-to-object moves, Eneo captures and hashes the inline source,
uploads under the existing publication reservation, verifies the complete
target, and then changes authority in one short database transaction that also
deletes the inline payload. For object-to-PostgreSQL moves, Eneo fully reads and
verifies the remote source before the transaction that inserts the inline
payload and changes authority. At every committed point, exactly one placement
is authoritative. A failure before the flip retries or stops without changing
the source; recovery after the flip proceeds forward.

An object-to-PostgreSQL flip registers the former remote key with the existing
orphan lifecycle. Keep the endpoint configured and the worker running until the
configured orphan grace has elapsed and two complete inventory observations
have allowed bounded deletion. Object-store configuration remains required
while any remote authority, staged move key, orphan candidate, or multipart
cleanup record exists. To retire an endpoint, first move all eligible content
inline, confirm **Admin > Storage** reports no active object-store content or
nonterminal moves, then allow those cleanup observations to finish before
removing configuration.

### Change the S3-compatible destination

Changing hosting provider does not require staging content in PostgreSQL — and
cannot, once any object exceeds the inline admission ceiling. Eneo does not
copy buckets; the operator copies with their own tooling and Eneo performs the
guarded switch. Object keys carry no endpoint or bucket, so a faithful copy is
readable immediately.

0. Confirm every backend and worker process runs the current release. The
   coordinated upgrade window above guarantees this; a pre-upgrade process
   does not hold the write fence the switch relies on.
1. Create an empty private bucket and a bucket-scoped application identity on
   the new service, and back up the current bucket.
2. Select `postgres_inline` for new writes in **Admin > Storage**, let queued
   moves and in-flight uploads finish, then select **Pause moves**. Both are
   required: an empty queue does not by itself stop a new move from starting
   mid-copy. New uploads above `OBJECT_CONTENT_INLINE_MAXIMUM_BYTES` fail
   during this window.
3. Copy only `v1/<deployment-id-hex>/` with `rclone copy --checksum` (never
   `sync`, which deletes at the destination) and preserve object metadata;
   Eneo enforces the stored media type on every read. Read the hex id from
   the current bucket — it is the filename under `v1/.eneo-bindings/`; on an
   environment-managed deployment it equals `OBJECT_CONTENT_DEPLOYMENT_ID`
   without dashes, while an Admin-created connection generates it internally.
   Never copy `v1/.eneo-bindings/` itself: that prefix holds the
   database-to-bucket marker and Eneo manages it per destination.
4. Compare both sides with `rclone check --download` until it reports no
   differences. `--download` reads and compares the actual bytes;
   `--checksum` falls back to size-only comparison when a hash is
   unavailable — the multipart-uploaded S3 case — and is not proof.
5. Use **Change destination** in **Admin > Storage**. Eneo probes the
   candidate, refuses a bucket paired with another Eneo installation, verifies
   the presence, size, and media type of every object the deployment still
   serves (byte equality is what step 4's `--download` comparison proves, and
   every read re-verifies the canonical SHA-256 and fails closed), and
   commits one fenced transaction that swaps the destination, preserves the
   deployment identity and every object key, archives the previous
   destination, resets both remote inventory cursors, and raises the
   connection revision. Work started against the previous destination cannot
   commit afterwards. No restart is needed. The verification contacts the new
   destination once per stored object, sixteen concurrently, so a large
   deployment's switch request runs for a while — keep it inside the
   maintenance window and raise any reverse-proxy request timeout in front of
   the backend if needed. An archived previous destination from an earlier
   change must be removed first, since the switch reuses that slot.
6. Select object storage for new writes again and resume moves, then let one
   complete inventory cycle run and confirm no `backend_missing` content. Full
   and range reads verify the canonical SHA-256, so an incomplete or corrupt
   copy surfaces instead of returning wrong bytes.

The previous destination stays archived until an administrator forgets it, and
**Switch back** returns to it under the same preconditions. It is a rollback,
not a second migration: once any object has been stored after the cutover, the
archived bucket can no longer serve every key and Eneo refuses it. Copy the
current bucket back and use **Change destination** instead. Eneo never deletes
objects or buckets on either destination: decommission the retired bucket at
the provider once the archived record is removed.

The switch is refused with a typed reason while new writes still target object
storage, storage moves are not paused, remote content is pending or
delete-pending, storage moves are nonterminal, an upload or cleanup lease is
live, or the candidate does not yet hold every object the deployment serves.
Retry after the worker has converged or the copy is complete.

The schema downgrade is available only before this feature has persisted a
move intent or `storage_moved` audit event. Once either exists, downgrade stops
without deleting the row, event, or feature schema. Restore the matching
application version and proceed forward; do not erase audit evidence to force a
downgrade.

Every inventory page must provide a complete, advancing pagination cursor.
Malformed or non-advancing pages fail that reconciliation run without
completing the inventory cycle or marking unseen rows missing. A complete
inventory marks absent `available` content failed; absent `retained` content
keeps its retention state while health reports `backend_missing`.
For multipart inventories, a truncated page must include both the next-key and
next-upload-ID markers, and the marker pair must advance.

## Capacity and operations

Alert before either PostgreSQL or object storage exhausts capacity. Monitor at
least bucket bytes, object count, free durable volume capacity, request latency
and errors, pending/failed/delete-pending counts, reconciliation lag, active
multipart uploads, and orphan-candidate age. Reconciliation concurrency is
bounded (1-32) and should be raised only after measuring PostgreSQL and endpoint
capacity. Size the backend/worker temporary volume for concurrent in-flight
upload and verified-read spools: memory use stops at the configured threshold,
while the remainder uses temporary disk until each upload or verified response
finishes. Account for one full remote read after each new remote write; this is
the provider-neutral integrity check before publication. Full user reads verify
and spool the full object. Range reads fetch and verify only the persisted upload
chunks covering the requested interval before response headers are sent. Their
transfer and temporary-disk cost is the requested interval plus at most two
chunk edges; existing rows migrated as one
whole-object chunk retain their previous full-verification cost. The chunk size
is captured per object, so later multipart tuning cannot invalidate existing
content. A range proves the chunks it covers; a full read still checks the
canonical full-object SHA-256 and can detect corruption elsewhere.

**Admin > Storage** reports two related measurements, not remaining capacity.
The file-content total is the sum of Eneo's recorded content sizes, excluding
content whose deletion has completed (`tombstoned`). Its PostgreSQL and
object-storage figures are parts of that total. **PostgreSQL on disk** comes
from PostgreSQL's catalog and covers the whole database, including inline file
content, searchable knowledge text and pgvector embeddings, tables, indexes,
and internal storage. It is therefore larger than the PostgreSQL file-content
figure and must not be added to the file-content total. The object-storage
figure is Eneo's recorded content
size, not provider-reported bucket usage, free capacity, version history, or
billing size. Use provider and host monitoring for those operational measures.

For PostgreSQL-inline content, monitor database size, WAL generation, backup
duration, connection-pool pressure, and the documented inline admission
ceiling. Reads are linear in payload size and use bounded chunks after the
database driver returns the bounded BYTEA value.

For the bundled single-node reference, durable capacity is the
`eneo_object_content_data` volume. Change `SEAWEEDFS_VOLUME_SIZE_LIMIT_MB` and
`SEAWEEDFS_GARBAGE_THRESHOLD` in `.env` when measured operations justify it;
they are storage layout settings, not application upload limits. Organizations
requiring multi-node availability should operate an external compatible service
with their normal redundancy, encryption, capacity, and disaster-recovery
controls.

## Paired backup and restore

An inline-only deployment needs the normal PostgreSQL backup: the control row
and payload are in the same transactional backup. Once any object-store content
exists, PostgreSQL and that byte plane form one recovery unit. Never call a
database-only or object-only backup complete in that state.

For the bundled reference service:

1. Put Eneo in maintenance and stop `backend` and `worker` so there are no new
   writes or lifecycle transitions.
2. Record the Eneo version, exact SeaweedFS manifest digest, stable deployment
   ID, PostgreSQL timestamp, and an operator backup ID. Do not record secrets.
3. Create a PostgreSQL logical dump, then stop `object-content` and archive its
   volume while writers remain stopped.
4. Checksum both artifacts and the manifest; copy them to independent durable
   storage with the same retention policy.
5. Restart the original pair only after both halves complete.

Example commands (the utility image is digest-pinned):

```bash
backup_id="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 0700 "backup-$backup_id"

docker compose stop backend worker
docker compose exec -T db pg_dump -U postgres -Fc eneo \
  >"backup-$backup_id/postgresql.dump"
docker compose stop object-content

docker run --rm \
  -v eneo_eneo_object_content_data:/data:ro \
  -v "$PWD/backup-$backup_id:/backup" \
  docker.io/library/alpine:3.22@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce \
  tar -C /data -czf "/backup/object-content.tar.gz" .

(cd "backup-$backup_id" && sha256sum postgresql.dump object-content.tar.gz \
  >SHA256SUMS)
```

Restore into an isolated environment first. Keep reconciliation and all writers
stopped, restore both halves from the same backup ID, preserve
`OBJECT_CONTENT_DEPLOYMENT_ID`, verify checksums, then start backend and worker.
Readiness also verifies the restored database/bucket marker pair. A missing or
mismatched marker means the halves are not the same recovery point; do not
create a replacement marker. Run a representative full/range read before
reopening traffic.

If PostgreSQL is newer than the object snapshot, rows can refer to missing
bytes; reads fail closed and reconciliation records the missing-object failure.
If the object snapshot is newer, bytes absent from PostgreSQL become orphan
candidates, but are not deleted until repeated complete inventories and the
configured grace period. Keep reconciliation stopped while correcting either
skew. Do not accept the skew as a new baseline.

For an external endpoint, replace the volume archive with the provider's
versioned bucket snapshot/export and prove that full bytes, metadata required by
the S3 subset, multipart state policy, and deletion state restore. Restore to a
quarantined bucket, run the endpoint conformance suite, then pair it with the
matching PostgreSQL backup.

## Upgrade and rollback

Before an Eneo or object-store upgrade, take a paired backup and retain the old
image digests. Upgrade the byte plane without changing endpoint semantics,
credentials, bucket, or deployment ID. Verify liveness, readiness, single and
multipart upload, range read, delete visibility, and reconciliation before
reopening traffic.

The deployment-policy migration creates revision 1 with `postgres_inline`
selected. It reads the four former upload-limit environment values once as
migration seeds. A present positive integer is preserved exactly; an absent
value uses the fresh-install default (10 MiB for session File, session image,
and knowledge File; 200 MiB for transcription audio). Blank, non-integer, zero,
or negative values stop the migration with a named remediation error. After the
migration, environment changes and restarts never overwrite the database
policy. During an upgrade, keep the old release's values available until
`db-init` succeeds, then remove them from active backend and worker
configuration. Fresh installations do not need them.

If a restore predates this migration, keep backend and worker stopped and run:

```bash
docker compose run --rm db-init
```

`db-init` runs Alembic `upgrade head`. The runtime does not create or repair a
missing policy table.

The store-binding migration (`202608061200`) moves the database-to-bucket
pairing facts to a per-destination table. It is the expand half of an
expand/contract change: the legacy columns stay in place with their
constraints so the later contract migration owns their removal explicitly.
Running pre-upgrade processes against the upgraded schema is unsupported —
this release upgrades through the coordinated maintenance window above, with
every pre-upgrade backend and worker stopped before Alembic runs.
Destination switching assumes every running writer holds the
store-generation fence, which pre-upgrade code does not, so never change
destination while any pre-upgrade process is running. The old columns are
dropped by a separate migration in a later release.

The File/Icon revisions perform schema setup followed by row-metadata inventory.
The first revision installs a database trigger that freezes legacy payload
columns and commits that fence. The following revision records one resumable
ledger item per legacy variant in separately committed, idempotent groups. It
refuses a non-UTF-8 database before writing the first group because legacy text
has UTF-8 canonical bytes. Inventory can run without retaining the schema
revision's exclusive locks on `files` or `icons`.
Both revisions keep every legacy byte and integrity column. The inventory scans
the owners and obtains the exact logical byte length of each frozen source
column without hashing, converting, or copying external payloads. It does not
contact object storage, hold an `ACCESS EXCLUSIVE` fence during the owner scan,
or drop the old columns. Normal reads prefer object-content
references and fall back to the frozen legacy variant only while its reference
is missing.

PostgreSQL inline remains the complete destination when no S3-compatible store
is configured. Choosing inline still needs capacity for the second verified
copy until the later contract and table rewrite reclaim the legacy storage, but
the work no longer blocks `db-init`. Choosing object storage avoids that second
payload copy in PostgreSQL; from the first authoritative remote payload onward,
backup and restore must include both PostgreSQL and the paired bucket.

The worker adopts inline legacy variants in resumable batches after startup.
Each item is leased, captured, and hashed once per processing attempt, then
committed with its content row, inline payload, exact File/Icon reference, and
completed ledger state in one short transaction. Crash recovery can read and
hash an item again after its lease expires. Owner deletion cancels only that
item; an invalid or oversized payload halts the campaign after other leased
items finish and leaves the frozen legacy source untouched for operator
recovery.

An inline campaign starts automatically when its remaining stored-byte estimate
is at most 5 GiB. Above that size, calculate PostgreSQL payload, WAL, backup,
replica, and safety headroom first, then set
`FILE_ICON_BACKFILL_INLINE_CAPACITY_ACK` to at least the reported estimate. The
acknowledgement does not reserve disk and the estimate is not peak allocation;
it records that the operator has accepted the capacity plan. When the current
Admin storage policy selects object storage, this inline worker does not start
or silently redirect the campaign. Remote adoption requires the verified
object-store adapter and changes the coordinated backup contract.
Set `FILE_ICON_BACKFILL_AUTO_INLINE_MAX_BYTES=0` when every non-empty inline
campaign must require explicit operator acknowledgement.
Waiting for capacity is non-fatal: the upgrade is complete, the application
continues serving frozen legacy File/Icon content, and the worker emits a
structured warning with the estimate and required acknowledgement on startup
and every scheduled tick.

Large installations can tune bounded throughput without changing application
or tenant policy:

| Variable                                      | Default | Meaning |
| --------------------------------------------- | ------: | ------- |
| `FILE_ICON_BACKFILL_AUTO_INLINE_MAX_BYTES`    |   5 GiB | Largest estimate that may start inline without an explicit capacity acknowledgement |
| `FILE_ICON_BACKFILL_INLINE_CAPACITY_ACK`      |       0 | Accepted inline estimate in bytes; must cover the current remaining estimate |
| `FILE_ICON_BACKFILL_BATCH_ROWS`               |     100 | Maximum ledger rows leased by one worker run |
| `FILE_ICON_BACKFILL_BATCH_BYTES`              |  32 MiB | Maximum summed stored-byte estimate per run; one larger first item is still claimed so it cannot be stranded |
| `FILE_ICON_BACKFILL_LEASE_SECONDS`            |     300 | Crash-recovery lease duration |
| `FILE_ICON_BACKFILL_RESUME_REVISION`          |       0 | Monotonic operator acknowledgement that the cause of a halted campaign was fixed; a strictly higher value requeues failed items once |
| `FILE_ICON_BACKFILL_MAX_ATTEMPTS`              |       3 | Processing attempts allowed before a repeatedly crashing item becomes a visible terminal failure |

Keep one item within `OBJECT_CONTENT_INLINE_MAXIMUM_BYTES`; the batch byte bound
does not override that per-content ceiling. The worker logs structured batch
counts after every non-empty run and logs the estimate and required action while
a campaign waits for capacity or is halted. Completion runs `ANALYZE` once on
the new content, payload, and reference tables before the campaign is marked
done.
A PostgreSQL 13 integration benchmark compared these defaults with 200 rows and
128 MiB at 1 GiB, then validated the larger candidate with 10 GiB of
incompressible legacy payloads. The candidate reduced scheduled batches from 33
to 9 per GiB without changing active throughput or WAL per payload byte. It is
not the default because the benchmark did not include concurrent application
traffic. The once-per-minute cadence deliberately limits database load while
the application remains online; it is not intended to maximize migration
throughput. Before increasing the batch limits, run a canary under
representative traffic and monitor foreground p95/p99 latency, errors, database
CPU and I/O, WAL/checkpoints, and batch duration. Restore the defaults if that
traffic regresses.
Only one worker replica may run a batch at a time. A PostgreSQL advisory lock
prevents minute jobs from overlapping and multiplying the configured byte and
memory bounds. Plan worst-case worker memory at roughly three times
`OBJECT_CONTENT_INLINE_MAXIMUM_BYTES`, plus an equally large temporary-file
allowance; measure the exact peak on the deployment's Python, asyncpg, and
PostgreSQL versions before raising that ceiling.
After correcting a halted campaign's stated cause, increase
`FILE_ICON_BACKFILL_RESUME_REVISION` and restart the worker configuration. Do
not reuse or lower a previous value. The worker records the accepted revision
in PostgreSQL, requeues failed items once, and still refuses to resume if the
Admin storage target differs from the campaign's frozen destination.
Completion is terminal and cached by each worker process; manual campaign
edits are unsupported and require a worker restart even during diagnosis.

This unreleased expand revision reuses Alembic revision ID `202607231700` and
replaces the former destructive normalization at that position. The inventory
revision `202607231745` was also corrected in place before release so capacity
uses logical source bytes consistently. A test or development environment that
started or completed either earlier revision must restore its pre-upgrade
database backup before using the new chain. The inventory commits groups
independently, and a rerun deliberately keeps existing ledger rows. Alembic also
cannot detect changed code behind an already-recorded revision ID.

After these revisions, recovery is forward: keep the legacy source frozen,
retry failed work, and resume from the ledger. A rollback to an older image is a
coordinated restore of its matching pre-upgrade database backup. Do not Alembic
stamp past the revision, attempt `alembic downgrade`, drop the trigger, edit
ledger state manually, or run an old File/Icon writer against the expanded
schema.

The operator status contract starts with this payload-free preflight query. It
excludes owners that were deleted and variants that already gained a durable
reference after the inventory snapshot. During the campaign, use ledger state
and structured worker logs for completed, failed, cancelled, and remaining
estimated work:

```sql
WITH actionable_pending AS (
    SELECT item.payload_size_estimate
    FROM file_icon_backfill_items AS item
    JOIN files AS file
      ON item.owner_kind = 'file' AND file.id = item.owner_id
    WHERE item.state = 'pending'
      AND NOT EXISTS (
          SELECT 1
          FROM file_content_references AS reference
          JOIN object_contents AS content ON content.id = reference.content_id
          WHERE reference.file_id = item.owner_id
            AND reference.variant = item.variant
            AND reference.ordinal = item.ordinal
            AND content.state = 'available'
      )

    UNION ALL

    SELECT item.payload_size_estimate
    FROM file_icon_backfill_items AS item
    JOIN icons AS icon
      ON item.owner_kind = 'icon' AND icon.id = item.owner_id
    WHERE item.state = 'pending'
      AND NOT EXISTS (
          SELECT 1
          FROM icon_content_references AS reference
          JOIN object_contents AS content ON content.id = reference.content_id
          WHERE reference.icon_id = item.owner_id
            AND reference.variant = item.variant
            AND content.state = 'available'
      )
)
SELECT count(*) AS pending_items,
       pg_size_pretty(coalesce(sum(payload_size_estimate), 0)::bigint)
           AS estimated_payload_bytes
FROM actionable_pending;
```

After the campaign starts, this query reports its frozen destination, recovery
state, and remaining ledger work without reading payloads. It scans the ledger,
so run it on demand for operator diagnosis rather than polling it from the
minute worker or a frequent monitor:

```sql
SELECT campaign.target_kind,
       campaign.state AS campaign_state,
       campaign.halt_reason,
       campaign.resume_revision,
       count(*) FILTER (WHERE item.state = 'pending') AS pending_items,
       count(*) FILTER (WHERE item.state = 'leased') AS leased_items,
       count(*) FILTER (WHERE item.state = 'failed') AS failed_items,
       count(*) FILTER (WHERE item.state = 'done') AS done_items,
       count(*) FILTER (WHERE item.state = 'cancelled') AS cancelled_items,
       pg_size_pretty(
           coalesce(sum(item.payload_size_estimate) FILTER (
               WHERE item.state NOT IN ('done', 'cancelled')
           ), 0)::bigint
       ) AS estimated_remaining_bytes
FROM file_icon_backfill_items AS item
LEFT JOIN file_icon_backfill_campaign AS campaign ON true
GROUP BY campaign.target_kind,
         campaign.state,
         campaign.halt_reason,
         campaign.resume_revision;
```

For a halted campaign, inspect at most the first 100 failed items before raising
the resume revision:

```sql
SELECT owner_kind,
       owner_id,
       variant,
       ordinal,
       attempts,
       last_error_code,
       last_error_detail
FROM file_icon_backfill_items
WHERE state = 'failed'
ORDER BY id
LIMIT 100;
```

The later range-verification revision uses the same maintenance window. It
backfills at most 10,000 unexpected pre-production object descriptors in one
transaction and aborts before changing schema or data when that bound is
exceeded. Released Eneo versions before this revision have no supported
File/Icon producer for these rows; contact Eneo before upgrading a deployment
that trips this guard.

Policy rollback does not move bytes. To stop new remote placement while keeping
the current version, select
`postgres_inline` in **Admin > Storage**. Existing remote content still needs
the endpoint, credentials, certificates, and paired backup. Selection never
migrates it implicitly.

Before rolling back to a release that predates the stored policy, export its
four current business limits and restore them as that old release's four legacy
environment settings; old code cannot read the singleton policy. Full
application/schema rollback then means restoring the previous image and the
matching database/object backup pair. Do not roll back only Alembic or only the
object store after writes have resumed. Do not introduce a second writable
store as a rollback path.

Authoritative external references:

- [S3 wire-protocol reference](https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html) (maintained by AWS; not an Eneo hosting dependency)
- [SeaweedFS S3 API](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API)
- [MinIO installation](https://docs.min.io/aistor/installation/)
- [MinIO S3 compatibility](https://docs.min.io/aistor/developers/s3-api-compatibility/)
- [MinIO policy management](https://docs.min.io/aistor/administration/iam/access/)
- [CycloneDX](https://cyclonedx.org/)
- [GitHub artifact attestations](https://docs.github.com/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
