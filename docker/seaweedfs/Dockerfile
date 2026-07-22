# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

# This image is built by Eneo from the exact upstream source archive below.
# It is not an upstream SeaweedFS image and does not claim upstream signing.
FROM --platform=$BUILDPLATFORM docker.io/library/golang:1.25.12-bookworm@sha256:ea341baa9bd5ba6784f6d7161ace70544349a6242d54d34a0fbfd2c4d51c9d58 AS builder

ARG TARGETARCH
ARG TARGETOS
ARG SOURCE_DATE_EPOCH=1784519823

WORKDIR /build
ADD --checksum=sha256:2e37f5d8980256e490324e3759d38437ecfee734f60aa3e75528b05f7d19460e \
    https://github.com/seaweedfs/seaweedfs/archive/875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa.tar.gz \
    /tmp/seaweedfs.tar.gz

RUN mkdir source \
    && tar --extract --gzip --file=/tmp/seaweedfs.tar.gz \
        --strip-components=1 --directory=source \
    && test "$(sha256sum /tmp/seaweedfs.tar.gz | cut -d ' ' -f 1)" \
        = "2e37f5d8980256e490324e3759d38437ecfee734f60aa3e75528b05f7d19460e"

WORKDIR /build/source/weed
RUN --mount=type=cache,target=/go/pkg/mod,sharing=locked \
    go mod download
RUN --mount=type=cache,target=/go/pkg/mod,sharing=locked \
    --mount=type=cache,target=/root/.cache/go-build,sharing=locked \
    CGO_ENABLED=0 GOOS="$TARGETOS" GOARCH="$TARGETARCH" \
    go build \
      -buildvcs=false \
      -mod=readonly \
      -trimpath \
      -ldflags="-buildid= -s -w -X github.com/seaweedfs/seaweedfs/weed/util/version.COMMIT=875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa" \
      -o /out/weed .

RUN mkdir -m 0700 /out/data \
    && cp /build/source/LICENSE /out/SEAWEEDFS-LICENSE

FROM gcr.io/distroless/static-debian13:nonroot@sha256:f7f8f729987ad0fdf6b05eeeae94b26e6a0f613bdf46feea7fc40f7bd72953e6

LABEL org.opencontainers.image.title="Eneo SeaweedFS object-content store" \
      org.opencontainers.image.description="Eneo-built reference S3-compatible byte store for object content" \
      org.opencontainers.image.source="https://github.com/eneo-ai/eneo" \
      org.opencontainers.image.vendor="Eneo" \
      org.opencontainers.image.version="4.40-eneo.1" \
      org.opencontainers.image.licenses="Apache-2.0" \
      io.eneo.upstream.name="SeaweedFS" \
      io.eneo.upstream.version="4.40" \
      io.eneo.upstream.commit="875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa" \
      io.eneo.upstream.tree="f6590c71c41ec414fc193b89e9d9dd586d39ad17" \
      io.eneo.upstream.archive.sha256="2e37f5d8980256e490324e3759d38437ecfee734f60aa3e75528b05f7d19460e"

COPY --from=builder --chown=65532:65532 /out/weed /usr/local/bin/weed
COPY --from=builder /out/SEAWEEDFS-LICENSE /licenses/seaweedfs/LICENSE
COPY --from=builder --chown=65532:65532 /out/data /data

ENV HOME=/data
WORKDIR /data
USER 65532:65532
VOLUME ["/data"]
EXPOSE 8333

# A deployment must supply an authenticated `mini` command explicitly. The
# inert default prevents an accidental anonymous object store.
ENTRYPOINT ["/usr/local/bin/weed"]
CMD ["version"]
