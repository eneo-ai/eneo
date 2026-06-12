"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { AddTextDialog, BlobTable } from "@/features/knowledge/blobs";
import {
  collectionBlobsQueryOptions,
  collectionQueryOptions
} from "@/features/knowledge/knowledge";
import { UploadBlobsDialog } from "@/features/knowledge/upload-dialog";
import { useSpace } from "@/features/spaces/use-space";

export function CollectionDetail({ collectionId }: { collectionId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const { data: collection } = useSuspenseQuery(collectionQueryOptions(browserApi, collectionId));
  const { data: blobs } = useSuspenseQuery(collectionBlobsQueryOptions(browserApi, collectionId));

  // Collections shared from another space (e.g. the organization space) are
  // read-only here; so are collections whose embedding model was disabled.
  const readonly = collection.space_id !== space.id;
  const modelDisabled = !space.embedding_models.some(
    (model) => model.id === collection.embedding_model.id
  );

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link
          href={`/spaces/${routeId}/knowledge?tab=collections`}
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" />
          {t("knowledge")}
        </Link>
        <PageHeader title={collection.name}>
          <AddTextDialog collectionId={collection.id} disabled={readonly || modelDisabled} />
          <UploadBlobsDialog
            collectionId={collection.id}
            currentBlobs={blobs}
            disabled={readonly || modelDisabled}
          />
        </PageHeader>
      </div>
      <BlobTable blobs={blobs} canEdit={!readonly} />
    </div>
  );
}
