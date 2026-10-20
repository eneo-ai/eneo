"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { HStack, Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";

/**
 * Asks for the new flow's name before the draft is created (a form dialog:
 * Enter creates, Escape cancels, a click outside does not lose the name).
 * The name is the only thing a person types; everything else is built in
 * the flow's chat.
 */
export function NewFlowDialog({
  open,
  pending,
  onCancel,
  onCreate
}: {
  open: boolean;
  pending: boolean;
  onCancel: () => void;
  onCreate: (name: string) => void;
}) {
  const t = useTranslations();
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const close = () => {
    setName("");
    setProblem(null);
    onCancel();
  };
  const create = () => {
    if (pending) return;
    const value = name.trim();
    if (!value) {
      setProblem(t("flow_new_name_required"));
      inputRef.current?.focus();
      return;
    }
    onCreate(value);
  };

  return (
    <Dialog isOpen={open} onOpenChange={(next) => !next && close()} purpose="form" width={440}>
      <Layout
        header={
          <DialogHeader
            title={t("flow_new_dialog_title")}
            subtitle={t("flow_new_dialog_description")}
            onOpenChange={(next) => !next && close()}
          />
        }
        content={
          <LayoutContent>
            <TextInput
              ref={inputRef}
              label={t("name")}
              value={name}
              onChange={(next) => {
                setName(next);
                if (problem) setProblem(null);
              }}
              onEnter={create}
              isRequired
              status={problem ? { type: "error", message: problem } : undefined}
            />
          </LayoutContent>
        }
        footer={
          <LayoutFooter>
            <HStack gap={2} hAlign="end">
              <Button label={t("cancel")} variant="secondary" onClick={close} />
              <Button
                label={t("create")}
                variant="primary"
                // Keeps focus while the draft is created; a second press is ignored.
                isLoading={pending}
                isInterruptible
                onClick={create}
              />
            </HStack>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
