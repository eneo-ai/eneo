"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { TextInput } from "@/components/astryx/text-input";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { useRemovalMutation } from "@/features/spaces/removal";
import type { SpaceSparse } from "@/features/spaces/space";

/**
 * Confirms deleting a space by typing its name (irreversible, WCAG 3.3.4).
 * Opened from a card's more-menu; `space` null means closed. Only the header
 * stays mounted while closed (Astryx names the dialog from the title present
 * when the <dialog> mounts); the form exists only while it is open.
 */
export function DeleteSpaceDialog({
  space,
  onClose
}: {
  space: SpaceSparse | null;
  onClose: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const formId = useId();
  const [typed, setTyped] = useState("");

  const deleteSpace = useRemovalMutation({
    mutationFn: (id: string) =>
      unwrap(browserApi.DELETE("/api/v1/spaces/{id}/", { params: { path: { id } } })),
    refresh: () => queryClient.invalidateQueries({ queryKey: ["spaces"] }),
    onRemoved: () => close()
  });

  function close() {
    setTyped("");
    onClose();
  }

  function onOpenChange(open: boolean) {
    if (!open && !deleteSpace.isPending) close();
  }

  const name = space?.name ?? "";
  const matches = space !== null && typed === name;

  return (
    <Dialog isOpen={space !== null} onOpenChange={onOpenChange} purpose="form" width={460}>
      <Layout
        height="auto"
        header={<DialogHeader title={t("delete_space")} onOpenChange={onOpenChange} />}
        content={
          space ? (
            <LayoutContent>
              <form
                id={formId}
                className="flex flex-col gap-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (matches) deleteSpace.mutate(space.id);
                }}
              >
                <p className="text-ax-text-secondary text-sm">
                  {t("confirm_delete_space_message", { space: name })}
                </p>
                <TextInput
                  label={t("enter_space_name_to_confirm")}
                  description={t("space_delete_type_name_hint", { name })}
                  value={typed}
                  onChange={setTyped}
                  autoComplete="off"
                />
              </form>
            </LayoutContent>
          ) : null
        }
        footer={
          space ? (
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={deleteSpace.isPending}
                  onClick={() => onOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="destructive"
                  label={deleteSpace.isPending ? t("deleting") : t("confirm_deletion")}
                  isDisabled={!matches || deleteSpace.isPending}
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
