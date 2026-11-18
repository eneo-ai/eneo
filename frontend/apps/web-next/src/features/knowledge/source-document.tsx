import { Button } from "@astryxdesign/core/Button";
import type { QueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, ExternalLink, FileText } from "lucide-react";
import { useEffect, useId, useRef } from "react";
import { Streamdown } from "streamdown";
import { useTranslations } from "use-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { PageFrame } from "@/components/composites/page-frame";
import { PageHeader } from "@/components/composites/page-header";
import { PageBar } from "@/components/shell/page-bar";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { readFresh } from "@/lib/api/query";
import { useCopy } from "@/lib/hooks/use-copy";
import { saveUrl, toastDownloadError } from "@/features/files/signed-file-url";
import { spaceQueryOptions, spaceRouteId, type Space } from "@/features/spaces/space";
import { sourceReferenceText } from "@/features/widget/widget-message-context";
import { isHttpUrl, linkHost } from "@/features/widget/urls";
import {
  collectionQueryOptions,
  infoBlobQueryOptions,
  websiteQueryOptions,
  type Collection,
  type Website
} from "./knowledge";
import { signedInfoBlobOriginalUrl } from "./signed-original-url";
import { SourceMetadataList } from "./source-metadata";

export type SourceDocument = {
  id: string;
  blob: Schema<"InfoBlobPublic"> | null;
  collection: Collection | null;
  website: Website | null;
  space: Space | null;
};

/** A missing or forbidden source gets the same response, without confirming its existence. */
function unavailableSource(error: unknown): null {
  if (error instanceof EneoApiError && [403, 404, 422].includes(error.status)) return null;
  throw error;
}

export async function loadSourceDocument(
  queryClient: QueryClient,
  api: EneoClient,
  id: string
): Promise<SourceDocument> {
  const blob = await readFresh(queryClient, infoBlobQueryOptions(api, id)).catch(unavailableSource);
  if (!blob) return { id, blob: null, collection: null, website: null, space: null };
  const [collection, website] = await Promise.all([
    blob.group_id
      ? readFresh(queryClient, collectionQueryOptions(api, blob.group_id)).catch(unavailableSource)
      : null,
    blob.website_id
      ? readFresh(queryClient, websiteQueryOptions(api, blob.website_id)).catch(unavailableSource)
      : null
  ]);
  const spaceId = collection?.space_id ?? website?.space_id;
  const space = spaceId
    ? await readFresh(queryClient, spaceQueryOptions(api, spaceId)).catch(unavailableSource)
    : null;
  return { id, blob, collection, website, space };
}

/** Resolves the reference a visitor can forward to a signed-in reader or administrator. */
export function SourceDocumentPage({ document: source }: { document: SourceDocument }) {
  const t = useTranslations();
  const { id, blob, collection, website, space } = source;
  const title = blob?.metadata.title || blob?.metadata.url || id;
  const reference = sourceReferenceText({ id, title }, location.origin);
  const { copy, isCopied } = useCopy();
  const titleId = useId();
  const contentsId = useId();
  const downloadRequest = useRef<AbortController | null>(null);
  useEffect(() => () => downloadRequest.current?.abort(), [id]);

  async function downloadOriginal() {
    if (downloadRequest.current && !downloadRequest.current.signal.aborted) return;
    const request = new AbortController();
    downloadRequest.current = request;
    try {
      const url = await signedInfoBlobOriginalUrl(browserApi, id, request.signal);
      if (!request.signal.aborted) saveUrl(url, title);
    } catch (error) {
      if (!request.signal.aborted) toastDownloadError(error, t);
    } finally {
      if (downloadRequest.current === request) downloadRequest.current = null;
    }
  }

  const sourceUrl = blob?.metadata.url;
  return (
    <>
      <PageBar
        parent={{ label: t("spaces"), href: "/spaces/list" }}
        title={t("document_lookup_title")}
        until="phone"
      />
      <PageFrame>
        <div className="flex max-w-4xl flex-col gap-6">
          <PageHeader title={t("document_lookup_title")} />
          {blob ? (
            <section
              aria-labelledby={titleId}
              className="border-ax-border rounded-ax-container flex flex-col gap-4 border p-4"
            >
              <h2 id={titleId} className="text-lg font-semibold break-words">
                {title}
              </h2>
              {collection && (
                <p className="text-ax-text-secondary text-sm">
                  {t("document_lookup_collection")}: {collection.name}
                </p>
              )}
              {website && (
                <p className="text-ax-text-secondary text-sm">
                  {t("document_lookup_website")}: {website.name || website.url}
                </p>
              )}
              <SourceMetadataList entries={blob.source_metadata ?? []} />
              {sourceUrl && <p className="text-ax-text-secondary text-sm break-all">{sourceUrl}</p>}
              <div className="flex flex-wrap gap-2">
                {blob.original_available && (
                  <Button
                    label={t("document_lookup_download_original")}
                    icon={<Download aria-hidden="true" />}
                    isInterruptible
                    clickAction={downloadOriginal}
                  />
                )}
                {sourceUrl && isHttpUrl(sourceUrl) && (
                  <Button
                    href={sourceUrl}
                    target="_blank"
                    rel="noreferrer"
                    label={t("widget_document_open_source", { host: linkHost(sourceUrl) })}
                    icon={<ExternalLink aria-hidden="true" />}
                  />
                )}
                {space && (
                  <Button
                    href={`/spaces/${spaceRouteId(space)}/knowledge`}
                    label={t("document_lookup_open_space", { space: space.name ?? "" })}
                  />
                )}
              </div>
              {!blob.original_available && (
                <p className="text-ax-text-secondary text-sm">
                  {t("document_lookup_original_unavailable")}
                </p>
              )}
            </section>
          ) : (
            <EmptyState
              title={t("document_lookup_not_found_title")}
              description={t("document_lookup_not_found_body")}
              icon={<FileText aria-hidden="true" />}
            />
          )}
          <dl className="flex flex-col gap-1 text-sm">
            <dt className="text-ax-text-secondary">{t("document_lookup_reference")}</dt>
            <dd className="break-all select-all">{reference}</dd>
          </dl>
          <div>
            <Button
              label={isCopied ? t("copied_to_clipboard") : t("copy_to_clipboard")}
              icon={isCopied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
              isInterruptible
              clickAction={async () => {
                await copy(reference);
              }}
            />
          </div>
          {blob && (
            <section
              aria-labelledby={contentsId}
              className="border-ax-border rounded-ax-container flex flex-col gap-4 border p-4"
            >
              <h2 id={contentsId} className="text-lg font-semibold">
                {t("document_lookup_contents")}
              </h2>
              <div className="min-w-0 text-sm">
                <Streamdown>{blob.text}</Streamdown>
              </div>
            </section>
          )}
        </div>
      </PageFrame>
    </>
  );
}
