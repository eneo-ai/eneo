"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@astryxdesign/core/TextInput";
import { getErrorMessage } from "@/lib/api/errors";
import { useSpace } from "@/features/spaces/use-space";
import { createFlow, refusalCode, storeFlow } from "./flows-api";

/** The core refuses a second active flow with the same name in a space. */
const NAME_TAKEN = "flow_name_taken";

/**
 * "Nytt flöde": a name and an optional description, then the empty draft
 * opens on its own page, where its steps are added by hand or in its chat.
 * Controlled by the caller, which renders the trigger. A refused name is
 * explained at the field; what the user typed stays.
 */
export function NewFlowDialog({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { space, routeId } = useSpace();
  const formId = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [nameProblem, setNameProblem] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () =>
      createFlow({
        spaceId: space.id,
        name: name.trim(),
        description: description.trim() || null
      }),
    onSuccess: (flow) => {
      storeFlow(queryClient, flow);
      close();
      router.push(`/spaces/${routeId}/flows/${flow.id}`);
    },
    onError: (error) => {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() =>
        setNameProblem(
          refusalCode(error) === NAME_TAKEN
            ? t("flows_new_name_taken")
            : t("flows_new_failed", { message: getErrorMessage(error, t) })
        )
      );
      nameRef.current?.focus();
    }
  });

  function close() {
    setName("");
    setDescription("");
    setNameProblem(null);
    onOpenChange(false);
  }

  function requestOpenChange(next: boolean) {
    if (!next && !create.isPending) close();
  }

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (create.isPending) return;
    if (!name.trim()) {
      flushSync(() => setNameProblem(t("flows_new_name_required")));
      nameRef.current?.focus();
      return;
    }
    create.mutate();
  }

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={480}>
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={t("flows_new_title")}
            subtitle={t("flows_new_description")}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          open ? (
            <LayoutContent>
              <form id={formId} onSubmit={submit} noValidate className="flex flex-col gap-4">
                <TextInput
                  ref={nameRef}
                  label={t("name")}
                  value={name}
                  onChange={(value) => {
                    setName(value);
                    if (nameProblem) setNameProblem(null);
                  }}
                  isRequired
                  htmlName="name"
                  autoComplete="off"
                  status={nameProblem ? { type: "error", message: nameProblem } : undefined}
                />
                <TextArea
                  label={t("description")}
                  description={t("flows_new_description_hint")}
                  value={description}
                  onChange={setDescription}
                  isOptional
                  rows={3}
                  htmlName="description"
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
                  isDisabled={create.isPending}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={t("flows_new_submit")}
                  // Busy, it stays enabled (aria-busy) and keeps focus; a
                  // second press is ignored.
                  isLoading={create.isPending}
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
