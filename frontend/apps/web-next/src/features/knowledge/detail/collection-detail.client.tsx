import { useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useRef } from "react";
import { BackLink } from "@/components/composites/back-link";
import { PageHeader } from "@/components/composites/page-header";
import { DockedActions } from "@/components/shell/docked-actions";
import { browserApi } from "@/lib/api/browser";
import { AddTextDialog, BlobTable } from "@/features/knowledge/blobs";
import {
  collectionBlobsQueryOptions,
  collectionQueryOptions
} from "@/features/knowledge/knowledge";
import { UploadBlobsButton } from "@/features/knowledge/upload-dialog";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";

export function CollectionDetail({ collectionId }: { collectionId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const headingId = useId();
  const { data: collection } = useSuspenseQuery(collectionQueryOptions(browserApi, collectionId));
  const { data: blobs } = useSuspenseQuery(collectionBlobsQueryOptions(browserApi, collectionId));

  // Collections shared from another space (e.g. the organization space) are
  // read-only here; so are collections whose embedding model was disabled.
  const readonly = collection.space_id !== space.id;
  const modelDisabled = !space.embedding_models.some(
    (model) => model.id === collection.embedding_model.id
  );

  return (
    // A deleted file's row takes its menu button with it: focus goes to the title.
    <RemovalFocusScope target={headingRef}>
      <div className="flex w-full flex-col gap-6">
        <div className="flex flex-col gap-1">
          <BackLink href={`/spaces/${routeId}/knowledge?tab=collections`} hideOnPhone>
            {t("knowledge")}
          </BackLink>
          <PageHeader title={collection.name} headingRef={headingRef} headingId={headingId}>
            <DockedActions label={t("space_knowledge_actions")}>
              <AddTextDialog
                collectionId={collection.id}
                disabled={readonly || modelDisabled}
                disabledReason={
                  modelDisabled && !readonly ? t("collection_enable_model_to_add_text") : undefined
                }
              />
              <UploadBlobsButton
                collectionId={collection.id}
                collectionName={collection.name}
                disabled={readonly || modelDisabled}
                disabledReason={
                  modelDisabled && !readonly ? t("collection_enable_model_to_add_text") : undefined
                }
              />
            </DockedActions>
          </PageHeader>
        </div>
        <BlobTable blobs={blobs} canEdit={!readonly} labelledBy={headingId} />
      </div>
    </RemovalFocusScope>
  );
}
