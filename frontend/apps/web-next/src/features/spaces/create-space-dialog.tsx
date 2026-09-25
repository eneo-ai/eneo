"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

/**
 * "Skapa yta": asks for a name, creates the space and opens its overview.
 * Controlled by the caller, which renders its own trigger. The form (and its
 * Namn field) only exists while the dialog is open; the header stays mounted
 * because Astryx names the dialog from the title present when it mounts.
 */
export function CreateSpaceDialog({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const router = useRouter();
  const queryClient = useQueryClient();
  const formId = useId();
  const [name, setName] = useState("");

  const createSpace = useMutation({
    mutationFn: (body: { name: string }) => unwrap(browserApi.POST("/api/v1/spaces/", { body })),
    onSuccess: (space) => {
      void queryClient.invalidateQueries({ queryKey: ["spaces"] });
      close();
      router.push(`/spaces/${space.id}/overview`);
    },
    onError: (error) => toastApiError(error, t)
  });

  function close() {
    setName("");
    onOpenChange(false);
  }

  function requestOpenChange(next: boolean) {
    if (!next && !createSpace.isPending) close();
  }

  const trimmed = name.trim();

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={440}>
      <Layout
        height="auto"
        header={<DialogHeader title={t("create_new_space")} onOpenChange={requestOpenChange} />}
        content={
          open ? (
            <LayoutContent>
              <form
                id={formId}
                onSubmit={(event) => {
                  event.preventDefault();
                  if (trimmed) createSpace.mutate({ name: trimmed });
                }}
              >
                <TextInput
                  label={t("name")}
                  value={name}
                  onChange={setName}
                  isRequired
                  autoComplete="off"
                />
              </form>
            </LayoutContent>
          ) : null
        }
        footer={
          open ? (
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={createSpace.isPending}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={createSpace.isPending ? t("loading") : t("create_space")}
                  isDisabled={!trimmed || createSpace.isPending}
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
