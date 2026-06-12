"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { WrapperActions } from "@/features/knowledge/integrations/actions";
import { wrapperDisplayName } from "@/features/knowledge/integrations/grouping";
import { IntegrationItemsTable } from "@/features/knowledge/integrations/table";
import { useSpace } from "@/features/spaces/use-space";

/**
 * All integration knowledge items in one SharePoint wrapper. The data lives
 * on the space object (prefetched by the space layout), so this derives from
 * useSpace; after the wrapper is deleted we navigate back to the tab.
 */
export function WrapperDetail({ wrapperId }: { wrapperId: string }) {
  const t = useTranslations();
  const router = useRouter();
  const { space, routeId } = useSpace();

  const items = space.knowledge.integration_knowledge_list.items.filter(
    (item) => item.wrapper_id === wrapperId && item.space_id === space.id
  );
  const first = items[0];
  const wrapperName = first ? wrapperDisplayName(first) : "";
  const permissions = first?.permissions ?? [];
  const backHref = `/spaces/${routeId}/knowledge?tab=integrations`;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link
          href={backHref}
          className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
        >
          <ChevronLeft className="size-4" />
          {t("integrations")}
        </Link>
        <PageHeader title={wrapperName}>
          <WrapperActions
            wrapperId={wrapperId}
            wrapperName={wrapperName}
            itemCount={items.length}
            canEdit={permissions.includes("edit")}
            canDelete={permissions.includes("delete")}
            onDeleted={() => router.push(backHref)}
          />
        </PageHeader>
      </div>
      {items.length === 0 ? (
        <EmptyState title={t("no_results")} />
      ) : (
        <IntegrationItemsTable
          rows={items.map((item) => ({
            kind: "item",
            item,
            embeddingModelId: item.embedding_model.id
          }))}
        />
      )}
    </div>
  );
}
