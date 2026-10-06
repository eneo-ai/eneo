"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, LayoutTemplate } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { Schema } from "@/lib/api/models";
import { useAppContext } from "@/components/providers/app-context";
import { markJustCreated } from "@/features/spaces/just-created";
import { createWithUniqueName } from "@/features/spaces/unique-name";
import { useSpace } from "@/features/spaces/use-space";
import { TemplateGalleryDialog } from "@/features/templates/template-gallery-dialog";

/**
 * Creates a blank app at once, named "Ny app" (numbered on a collision), and
 * opens its editor, which focuses the name: no name dialog in between. With
 * templates enabled, a split-button menu also offers the template gallery.
 */
export function CreateAppButton() {
  const t = useTranslations();
  const router = useRouter();
  const { settings } = useAppContext();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<"template" | null>(null);

  const create = useMutation({
    mutationFn: ({
      appName,
      fromTemplate
    }: {
      appName: string;
      fromTemplate?: Schema<"TemplateCreate">;
    }) =>
      createWithUniqueName(appName, (candidate) =>
        unwrap(
          browserApi.POST("/api/v1/spaces/{id}/applications/apps/", {
            params: { path: { id: space.id } },
            body: {
              name: candidate,
              ...(fromTemplate ? { from_template: fromTemplate } : {})
            }
          })
        )
      ),
    onSuccess: (app, { fromTemplate }) => {
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      setDialog(null);
      if (!fromTemplate) markJustCreated("app", app.id);
      router.push(`/spaces/${routeId}/apps/${app.id}/edit`);
    },
    onError: (error) => toastApiError(error, t)
  });

  // Busy, the button stays enabled so it keeps focus; a second press is ignored.
  const createBlank = () => {
    if (!create.isPending) create.mutate({ appName: t("new_app_default_name") });
  };
  const busy = create.isPending || undefined;

  return (
    <>
      {settings.using_templates ? (
        <div className="flex">
          <Button className="rounded-r-none" aria-busy={busy} onClick={createBlank}>
            {t("create_app")}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                className="rounded-l-none border-l"
                aria-label={t("ui_more_ways_to_create")}
              >
                <ChevronDown className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setDialog("template")}>
                <LayoutTemplate className="size-4" /> {t("start_with_template")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ) : (
        <Button aria-busy={busy} onClick={createBlank}>
          {t("create_app")}
        </Button>
      )}
      <TemplateGalleryDialog
        templateKind="app"
        createLabel={t("create_app")}
        open={dialog === "template"}
        onOpenChange={(next) => setDialog(next ? "template" : null)}
        pending={create.isPending}
        onCreate={(fromTemplate, templateName) =>
          create.mutateAsync({ appName: templateName, fromTemplate }).then(() => undefined)
        }
      />
    </>
  );
}
