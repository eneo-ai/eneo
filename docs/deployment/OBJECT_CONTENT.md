# Durable object content

The primary, navigable operator guide is [Choose Content
Storage](https://docs.eneo.ai/guides/object-content-storage). This file is the
offline reference shipped beside the Compose templates.

## TL;DR

- Eneo runs normally without S3-compatible storage. PostgreSQL inline is the
  default.
- File and Icon now use the shared content identity, typed variants, integrity,
  and lifecycle owner. New writes in this slice remain PostgreSQL inline.
- PostgreSQL owns identity, SHA-256, size/type, references, access, retention,
  and lifecycle. Exactly one selected backend owns each payload.
- Enabling SeaweedFS, MinIO, or another endpoint does not move existing bytes.
  Placement and migration are explicit later workflows.
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

The default deployment uses PostgreSQL-inline storage and does not start
SeaweedFS or require S3-compatible configuration. Operators can enable the
bundled profile or connect an external endpoint when object size, capacity, or
availability requirements justify it. There is no production filesystem
backend, automatic fallback, dual write, public object URL, provider registry,
or provider-specific product branch.

File and Icon are the first adopted product owners. Their legacy bytes are
copied in bounded batches, verified against PostgreSQL-owned SHA-256 and size,
switched to concrete typed references, and only then removed from the old
columns. New File and Icon content remains PostgreSQL inline in this slice.
InfoBlob generations, Flow artifacts, and administrator-selected placement are
separate follow-up work.

## Choose the endpoint

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
- object deletion with observable not-found convergence;
- SHA-256 part/composite semantics for multipart where requested.

Native range support is an endpoint conformance gate. Eneo's application read
path still full-GETs and verifies the canonical digest before slicing a range
from its local spool.

Eneo computes the canonical full-byte SHA-256 incrementally over its own upload
stream. S3 ETags, multipart composite checksums, CRCs, and user metadata never
replace that digest. A bypassing upload, migration, restore, or ambiguous
reconciliation must be fully streamed back and rehashed before it becomes
available.

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
deduplication.

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
      "Action": [
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads"
      ],
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

HTTP 200 alone can also represent degraded remote storage while inline content
remains available, so deployment checks must verify the explicit code.

Before production traffic, validate a staging Eneo deployment against the exact
MinIO version and configuration you will operate. Exercise single and multipart
upload (including ordered part listing), full and range read, delete visibility,
bucket isolation, TLS trust, and paired restore; Eneo's object-content
integration suite defines those expected behaviors. Align MinIO object
versioning, lifecycle rules, snapshots, and immutable retention with Eneo's
deletion and legal-retention policy; an object-store rule must not silently keep
purged content longer than approved.

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
bounds PostgreSQL row and process memory exposure; it is documented and
configurable, not a hidden business limit. Lowering it affects new writes, not
reads of existing rows. User-facing upload limits remain business settings
owned by application/admin configuration. Keep this ceiling at least as large
as the largest File upload limit; backend and worker fail during startup when
those settings conflict, before an upload can be accepted and then rejected by
storage.

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

Object content has five explicit runtime outcomes:

| Deployment state | Process | Readiness / operations |
| --- | --- | --- |
| Remote settings absent; no active object-store rows | Starts inline-capable | Healthy `object_store_not_configured`; local work continues |
| Remote settings absent; active object-store rows exist | Starts fail-closed | `configuration_required`; remote content is not stranded silently |
| Any blank, partial, or invalid remote settings | Startup fails | Clear configuration validation error |
| Complete settings; PostgreSQL and endpoint available | Starts inline + object-store capable | Healthy `ready` |
| Complete settings; endpoint temporarily unavailable | Stays live | Overall readiness remains 200/degraded; object-store operations return typed 503, inline operations continue |
| Reachable bucket not paired with this PostgreSQL database | Startup fails | `configuration_required`; reconciliation does not mutate rows or objects |

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

Uploads and deletes record durable PostgreSQL intent before remote work.
Bounded leases, idempotency, retries, multipart abort records, tombstones, and
two-sided reconciliation converge after a process or network failure. Delete
intent is irreversible. A final reference cannot delete content while a hold or
minimum-retention boundary blocks it.

A new inline record commits its verified payload, immediately available control
row, and exactly one first File, InfoBlob, or Icon reference in the same
transaction. A new object-store record commits its descriptor, `pending`
control row, and exactly one first reference before remote upload begins. Later
references require `available`. Deferred PostgreSQL constraints reject an
ownerless record, a mismatched backend, or multiple first references.

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
finishes. A range read verifies and spools the full object before serving the
requested interval, so size temporary disk for the largest permitted objects
multiplied by measured peak read concurrency.

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

For the File/Icon normalization upgrade, stop backend and worker producers
before Alembic starts and do not restart them until the migration succeeds. If
it stops, retry the migration before accepting new uploads; intervening writes
make the retry fail closed rather than guess which authority is valid.

Rollback means restoring the previous application/image version and the matching
database/object backup pair. Do not roll back only Alembic or only the object
store after writes have resumed. Do not introduce a second writable store as a
rollback path.

Authoritative external references:

- [S3 wire-protocol reference](https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html) (maintained by AWS; not an Eneo hosting dependency)
- [SeaweedFS S3 API](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API)
- [MinIO installation](https://docs.min.io/aistor/installation/)
- [MinIO S3 compatibility](https://docs.min.io/aistor/developers/s3-api-compatibility/)
- [MinIO policy management](https://docs.min.io/aistor/administration/iam/access/)
- [CycloneDX](https://cyclonedx.org/)
- [GitHub artifact attestations](https://docs.github.com/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
