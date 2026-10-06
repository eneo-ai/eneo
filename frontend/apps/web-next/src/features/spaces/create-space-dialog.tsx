"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { TextInput } from "@/components/astryx/text-input";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

/**
 * "Skapa yta", the one create-space flow (the spaces list, the SideNav "+"
 * and the ⌘K palette): asks for a name, creates the space, refreshes the
 * spaces queries and opens the new space's overview. Controlled by the
 * caller, which renders its own trigger. The form (and its Namn field) only
 * exists while the dialog is open; the header stays mounted because Astryx
 * names the dialog from the title present when it mounts.
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
  const inputRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [showError, setShowError] = useState(false);

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
    setShowError(false);
    onOpenChange(false);
  }

  function requestOpenChange(next: boolean) {
    if (!next && !createSpace.isPending) close();
  }

  // An empty name is explained at the field (WCAG 3.3.1, 3.3.3), not
  // prevented with a disabled button that says nothing.
  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (createSpace.isPending) return;
    const trimmed = name.trim();
    if (!trimmed) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setShowError(true));
      inputRef.current?.focus();
      return;
    }
    createSpace.mutate({ name: trimmed });
  }

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={440}>
      <Layout
        height="auto"
        header={<DialogHeader title={t("create_new_space")} onOpenChange={requestOpenChange} />}
        content={
          open ? (
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
                  label={t("create_space")}
                  // Busy, it stays enabled (aria-busy) and keeps focus; a
                  // second press is ignored.
                  isLoading={createSpace.isPending}
                  isInterruptible
                />
              </div>
            </LayoutFooter>
          ) : null
        }
      />
    </Dialog>
  );
}
