"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { HStack, Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

/**
 * "Skapa yta" from the SideNav and the palette: the same flow as the spaces
 * list (POST /spaces/, refresh the spaces queries, open the new space's
 * overview). The form only exists while the dialog is open, so a closed
 * dialog never leaves a second "Namn" field in the page.
 */
export function CreateSpaceDialog({
  isOpen,
  onOpenChange
}: {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
}) {
  const t = useTranslations();
  const router = useRouter();
  const queryClient = useQueryClient();
  const formId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [showError, setShowError] = useState(false);

  function close() {
    onOpenChange(false);
    setName("");
    setShowError(false);
  }

  const createSpace = useMutation({
    mutationFn: (body: { name: string }) => unwrap(browserApi.POST("/api/v1/spaces/", { body })),
    onSuccess: (space) => {
      void queryClient.invalidateQueries({ queryKey: ["spaces"] });
      close();
      router.push(`/spaces/${space.id}/overview`);
    },
    onError: (error) => toastApiError(error, t)
  });

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setShowError(true);
      inputRef.current?.focus();
      return;
    }
    createSpace.mutate({ name: trimmed });
  }

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => (open ? onOpenChange(true) : close())}
      purpose="form"
      width={440}
      aria-label={t("create_new_space")}
    >
      {isOpen ? (
        <Layout
          header={<DialogHeader title={t("create_new_space")} onOpenChange={() => close()} />}
          content={
            <LayoutContent>
              <form id={formId} onSubmit={submit} noValidate>
                <TextInput
                  ref={inputRef}
                  label={t("name")}
                  value={name}
                  onChange={(value) => {
                    setName(value);
                    if (value.trim()) setShowError(false);
                  }}
                  isRequired
                  htmlName="name"
                  autoComplete="off"
                  status={
                    showError
                      ? { type: "error", message: t("shell_create_space_name_required") }
                      : undefined
                  }
                />
              </form>
            </LayoutContent>
          }
          footer={
            <LayoutFooter>
              <HStack gap={2} hAlign="end">
                <Button label={t("cancel")} variant="secondary" onClick={close} />
                <Button
                  type="submit"
                  form={formId}
                  label={t("create_space")}
                  variant="primary"
                  isLoading={createSpace.isPending}
                />
              </HStack>
            </LayoutFooter>
          }
        />
      ) : null}
    </Dialog>
  );
}
