import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, LayoutTemplate } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { Schema } from "@/lib/api/models";
import { useAppContext } from "@/components/providers/app-context";
import { markJustCreated } from "@/features/spaces/just-created";
import { createWithUniqueName } from "@/features/spaces/unique-name";
import { useSpace } from "@/features/spaces/use-space";
import { TemplateGalleryDialog } from "@/features/templates/template-gallery-dialog";
import { cn } from "@/lib/utils";

/**
 * Split button: the primary action creates a blank assistant at once, named
 * "Ny assistent" (numbered on a collision), and opens its editor, which
 * focuses the name. No name dialog in between: the editor's first field is
 * that same name. The chevron menu also offers — when the tenant has templates
 * enabled — creation from a template gallery (passes from_template), which
 * still asks for the template and name.
 * `secondary` makes it small and unfilled where it is not the screen's primary
 * action (a phone's space overview; the tab's docked button is).
 */
export function CreateChatAppMenu({
  secondary = false,
  isHiddenOnPhone = false
}: {
  secondary?: boolean;
  /** Only the buttons go: a dialog they opened stays open if the screen becomes a phone's. */
  isHiddenOnPhone?: boolean;
}) {
  const t = useTranslations();
  const router = useRouter();
  const { space, routeId } = useSpace();
  const { settings } = useAppContext();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<"template" | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });

  const createAssistant = useMutation({
    mutationFn: ({
      name,
      fromTemplate
    }: {
      name: string;
      fromTemplate?: Schema<"TemplateCreate">;
      openEditor?: boolean;
    }) =>
      createWithUniqueName(name, (candidate) =>
        unwrap(
          browserApi.POST("/api/v1/spaces/{id}/applications/assistants/", {
            params: { path: { id: space.id } },
            body: {
              name: candidate,
              ...(fromTemplate ? { from_template: fromTemplate } : {})
            }
          })
        )
      ),
    onSuccess: (assistant, { fromTemplate, openEditor = !fromTemplate }) => {
      invalidate();
      setDialog(null);
      if (openEditor) {
        if (!fromTemplate) markJustCreated("assistant", assistant.id);
        router.push(`/spaces/${routeId}/assistants/${assistant.id}/edit`);
      }
    },
    onError: (error) => toastApiError(error, t)
  });

  // Busy, the buttons stay enabled so they keep focus; a second press is ignored.
  const pending = createAssistant.isPending;
  const createBlankAssistant = () => {
    if (!pending) createAssistant.mutate({ name: t("new_assistant_default_name") });
  };

  const variant = secondary ? "secondary" : "primary";
  const size = secondary ? "sm" : "md";

  return (
    <>
      <div className={cn("flex max-w-full", isHiddenOnPhone && "phone:hidden")}>
        <Button
          label={t("create_assistant")}
          variant={variant}
          size={size}
          // Astryx keeps a label on one line at a fixed height and cuts it with an
          // ellipsis; this one may shrink at 320 px, so it wraps instead (1.4.4).
          // A line and py-1 fit the element height, which min-h keeps, so one
          // line is exactly as tall as the menu button beside it.
          className={`h-auto min-w-0 shrink grow rounded-r-none py-1 text-center whitespace-normal ${
            secondary ? "min-h-(--size-element-sm)" : "min-h-(--size-element-md)"
          }`}
          isLoading={createAssistant.isPending}
          isInterruptible
          onClick={createBlankAssistant}
        />
        <DropdownMenu
          button={{
            label: t("ui_more_ways_to_create"),
            icon: <ChevronDown aria-hidden="true" />,
            isIconOnly: true,
            variant,
            size,
            // As tall as the label beside it when that wraps (h-auto, stretched); an
            // icon button's width follows its height, so it keeps its own minimum.
            className: `h-auto self-stretch rounded-l-none border-l pointer-coarse:min-w-11 ${
              secondary ? "min-w-(--size-element-sm)" : "min-w-(--size-element-md)"
            }`
          }}
          hasChevron={false}
          alignment="end"
          items={[
            {
              label: t("create_new_assistant"),
              icon: <Bot aria-hidden="true" />,
              onClick: createBlankAssistant
            },
            ...(settings.using_templates
              ? [
                  {
                    label: t("start_with_template"),
                    icon: <LayoutTemplate aria-hidden="true" />,
                    onClick: () => setDialog("template")
                  }
                ]
              : [])
          ]}
        />
      </div>
      <TemplateGalleryDialog
        templateKind="assistant"
        createLabel={t("create_assistant")}
        open={dialog === "template"}
        onOpenChange={(open) => setDialog(open ? "template" : null)}
        pending={createAssistant.isPending}
        onCreate={(fromTemplate, name, openEditor) =>
          createAssistant.mutateAsync({ name, fromTemplate, openEditor }).then(() => undefined)
        }
      />
    </>
  );
}
