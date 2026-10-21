"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@/components/astryx/text-input";
import type { components } from "@/lib/api/schema";
import { updateFlowEditor } from "../flows-api";
import { flowRefusalMessage } from "../flow-refusals";
import { orderWithNewStep } from "../flow-steps";

type FlowPublic = components["schemas"]["FlowPublic"];

/**
 * Placeholder for the dialog that adds a configured step, which is built on
 * its own and replaces this file. Until then it adds a named step that
 * processes the text before it with AI, at `position` (1-based), so the
 * flow page's add-at-a-position path can be used end to end.
 */
export function AddStepDialog({
  flow,
  position,
  open,
  onOpenChange,
  onSaved
}: {
  flow: FlowPublic;
  position: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (flow: FlowPublic) => void;
}): React.JSX.Element {
  const t = useTranslations();
  const formId = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const add = useMutation({
    mutationFn: () =>
      updateFlowEditor(flow.id, {
        expected_revision: flow.draft_revision,
        definition: {},
        new_steps: [
          {
            name: name.trim(),
            configuration: {
              input_source: position <= 1 ? "flow_input" : "previous_step",
              input_type: "text",
              output_mode: "pass_through",
              output_type: "text"
            }
          }
        ],
        step_order: orderWithNewStep(flow.steps, position)
      }),
    onSuccess: (updated) => {
      close();
      onSaved(updated);
    },
    onError: (error) => {
      flushSync(() => setProblem(flowRefusalMessage(error, flow.steps, t)));
      nameRef.current?.focus();
    }
  });

  function close() {
    setName("");
    setProblem(null);
    onOpenChange(false);
  }

  function requestOpenChange(next: boolean) {
    if (!next && !add.isPending) close();
  }

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (add.isPending) return;
    if (!name.trim()) {
      flushSync(() => setProblem(t("flows_add_step_name_required")));
      nameRef.current?.focus();
      return;
    }
    add.mutate();
  }

  return (
    <Dialog isOpen={open} onOpenChange={requestOpenChange} purpose="form" width={440}>
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={t("flows_add_step_title", { position })}
            subtitle={t("flows_add_step_description")}
            onOpenChange={requestOpenChange}
          />
        }
        content={
          open ? (
            <LayoutContent>
              <form id={formId} onSubmit={submit} noValidate>
                <TextInput
                  ref={nameRef}
                  label={t("name")}
                  value={name}
                  onChange={(value) => {
                    setName(value);
                    if (problem) setProblem(null);
                  }}
                  isRequired
                  autoComplete="off"
                  status={problem ? { type: "error", message: problem } : undefined}
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
                  isDisabled={add.isPending}
                  onClick={() => requestOpenChange(false)}
                />
                <Button
                  type="submit"
                  form={formId}
                  variant="primary"
                  label={t("flows_add_step_submit")}
                  isLoading={add.isPending}
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
