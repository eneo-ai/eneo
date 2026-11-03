import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, LayoutTemplate } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
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
 * An app cannot run without both a completion and a transcription model, so
 * until the space has them, either way says what is missing instead.
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

  const missingModels = [
    space.completion_models.length === 0 && t("completion_models_warning_app"),
    space.transcription_models.length === 0 && t("transcription_models_warning_app")
  ].filter((warning) => warning !== false);
  const blocked = () => {
    for (const warning of missingModels) toast.warning(warning, { id: warning });
    return missingModels.length > 0;
  };

  // Busy, the button stays enabled so it keeps focus; a second press is ignored.
  const createBlank = () => {
    if (!create.isPending && !blocked()) create.mutate({ appName: t("new_app_default_name") });
  };
  const openGallery = () => {
    if (!blocked()) setDialog("template");
  };
  const createButton = (className?: string) => (
    <Button
      label={t("create_app")}
      variant="primary"
      className={className}
      isLoading={create.isPending}
      isInterruptible
      onClick={createBlank}
    />
  );

  return (
    <>
      {settings.using_templates ? (
        <div className="flex">
          {createButton("rounded-r-none")}
          <DropdownMenu
            button={{
              label: t("ui_more_ways_to_create"),
              icon: <ChevronDown aria-hidden="true" />,
              isIconOnly: true,
              variant: "primary",
              className: "rounded-l-none border-l"
            }}
            hasChevron={false}
            alignment="end"
            items={[
              {
                label: t("start_with_template"),
                icon: <LayoutTemplate aria-hidden="true" />,
                onClick: openGallery
              }
            ]}
          />
        </div>
      ) : (
        createButton()
      )}
      <TemplateGalleryDialog
        templateKind="app"
        createLabel={t("create_app")}
        open={dialog === "template"}
        onOpenChange={(next) => setDialog(next ? "template" : null)}
        pending={create.isPending}
        onCreate={(fromTemplate, templateName) =>
          // A model can go while the gallery is open; a rejection keeps its draft.
          blocked()
            ? Promise.reject(new Error("The space lacks a model an app needs"))
            : create.mutateAsync({ appName: templateName, fromTemplate }).then(() => undefined)
        }
      />
    </>
  );
}
