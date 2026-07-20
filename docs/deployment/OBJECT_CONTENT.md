# Durable object content

Eneo separates durable file identity from durable file bytes. PostgreSQL is the
control plane: it owns typed content identity, media type, canonical SHA-256,
exact size, authorization references, holds, retention, lifecycle state, audit,
and reconciliation facts. One private S3-compatible bucket is the byte plane.
It owns original and derived byte streams, but it never becomes the source of
truth for authorization or lifecycle.

The separation is mandatory for consumers that adopt object content. There is
no production filesystem backend, PostgreSQL byte fallback, dual write, public
object URL, provider registry, or provider-specific product branch. Object keys
are opaque, deployment-scoped values; they contain neither tenant nor filename.
The bucket and key are never returned by ordinary APIs.

The foundation can remain disabled during rollout while no durable
object-content records exist. Disable it only by omitting **every**
`OBJECT_CONTENT_*` application setting. Setting one or more values activates
strict validation; a blank, partial, or invalid configuration stops startup.
This is a deployment capability, not a tenant or administrator feature toggle.

## Choose the endpoint

The reference Compose deployment starts an Eneo-built SeaweedFS 4.39 service on
the private `object_content_net`. The image is built from upstream commit
`db42bb49757b459551607939807017d7a9d5a94a`, not from an upstream image. Eneo
pins the source archive, build image, runtime image, and GitHub Actions; scans
the exact amd64 and arm64 image digests; publishes CycloneDX 1.6 and SPDX SBOMs;
and signs provenance and SBOM attestations with Eneo's GitHub Actions identity.
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
signing region, bucket, and credentials in `.env`, then start the stack with:

```bash
docker compose up -d --scale object-content=0
```

Keep `ENEO_SEAWEEDFS_IMAGE` set to the release's verified digest because Compose
validates the complete file during configuration. At scale zero that image is
not started and Eneo connects only to the explicit external endpoint.

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

Start Eneo without the bundled service, then verify readiness:

```bash
docker compose up -d --scale object-content=0
curl --fail https://eneo.example.eu/api/readyz
```

Before production traffic, validate a staging Eneo deployment against the exact
MinIO version and configuration you will operate. Exercise single and multipart
upload (including ordered part listing), full and range read, delete visibility,
bucket isolation, TLS trust, and paired restore; Eneo's object-content
integration suite defines those expected behaviors. Align MinIO object
versioning, lifecycle rules, snapshots, and immutable retention with Eneo's
deletion and legal-retention policy; an object-store rule must not silently keep
purged content longer than approved.

## Configuration states

The reference Compose installation enables the bundled service, so copy
`.env.template`, set mode `0600`, and fill every blank. Pin
`ENEO_SEAWEEDFS_IMAGE` to the exact manifest digest recorded in the Eneo
release's `IMAGE-DIGESTS.txt`. Copy the digest reference from its single
`seaweedfs manifest` row, not either architecture-specific SBOM row. There is
deliberately no mutable-tag default.

A custom deployment that has not adopted an object-backed feature may omit all
`OBJECT_CONTENT_*` settings. Backend and worker then start with the capability
disabled, `/api/readyz` reports `object_content.code=disabled`, reconciliation
performs no S3 work, and authenticated settings expose
`object_content_enabled=false`. Eneo verifies PostgreSQL before accepting this
state. If any non-tombstoned object-content row exists, startup and subsequent
probes fail closed until the complete configuration is restored. This prevents
pending uploads, retention work, or deletes from being silently stranded.

Do not model disabled with blank values. Omit the variables entirely. Once a
producer stores its first durable object-content record, the compatible byte
plane is required for that deployment and there is no filesystem or PostgreSQL
byte fallback.

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

Transport, bounded-memory, multipart, and reconciliation tuning lives in
`env_backend.env`. These are operator settings, not product policy. Eneo does
not impose a hidden object-content file-size cap; user-facing upload limits are
business settings owned by the application/admin configuration.

## Runtime and health

Object content has four explicit runtime outcomes:

| Deployment state | Process | Readiness / operations |
| --- | --- | --- |
| All application settings absent and no active rows | Starts disabled | Healthy `disabled`; dependent operations return typed `object_content_disabled` 503 |
| Any blank, partial, or invalid settings | Startup fails | Clear configuration validation error |
| Complete valid settings; PostgreSQL and bucket available | Starts enabled | Healthy `ready` |
| Complete valid settings; PostgreSQL or bucket unavailable | Stays alive | Unhealthy readiness and typed 503; no fallback |
| Reachable bucket not paired with this PostgreSQL database | Startup fails | `configuration_required`; reconciliation does not mutate rows or objects |

Disabled with active PostgreSQL content is an invalid fifth state: startup,
readiness, and the scheduled safety check fail closed with
`configuration_required`. Each API and worker process evaluates its deployment
environment independently, so supply the same settings to all of them. Before
the first active row, mixed process configuration is visible through the
capability/readiness projection; after a row exists, the disabled process fails
the guard. Process liveness itself does not depend on the object store.
Readiness uses a separate short-timeout S3 client when enabled. Health output
includes only a status and stable code, never endpoint, bucket, key,
credentials, or provider details.

The first enabled startup creates one random database identity in PostgreSQL
and atomically places its private marker in the configured bucket. Later
startups, readiness probes, and every reconciliation run require that exact
pair. A missing or different marker is never adopted or overwritten after
confirmation. This prevents a reachable empty or foreign bucket from being
treated as this deployment's byte plane. The marker is an internal safety
invariant, not an administrator or tenant setting, and must be included in
bucket backups.

Uploads and deletes record durable PostgreSQL intent before remote work.
Bounded leases, idempotency, retries, multipart abort records, tombstones, and
two-sided reconciliation converge after a process or network failure. Delete
intent is irreversible. A final reference cannot delete content while a hold or
minimum-retention boundary blocks it.

Object-content reconciliation is a queue-neutral async task. The current worker
registers and schedules it with ARQ; the lifecycle implementation does not
import ARQ. Replacing ARQ with another worker implementation therefore changes
the scheduling/registration adapter, not S3 or lifecycle logic.

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

For the bundled single-node reference, durable capacity is the
`eneo_object_content_data` volume. Change `SEAWEEDFS_VOLUME_SIZE_LIMIT_MB` and
`SEAWEEDFS_GARBAGE_THRESHOLD` in `.env` when measured operations justify it;
they are storage layout settings, not application upload limits. Organizations
requiring multi-node availability should operate an external compatible service
with their normal redundancy, encryption, capacity, and disaster-recovery
controls.

## Paired backup and restore

PostgreSQL and the byte plane form one recovery unit. Never call a database-only
or object-only backup complete.

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
