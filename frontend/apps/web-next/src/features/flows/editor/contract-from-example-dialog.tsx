"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Token } from "@astryxdesign/core/Token";
import { ClipboardPaste } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import {
  contractFromExample,
  EXAMPLE_MAX_CHARACTERS,
  EXAMPLE_MAX_FIELDS,
  type ExampleProblem,
  type ExampleShape
} from "./contract-from-example";
import type { JsonObject } from "./step-types";

type Translate = ReturnType<typeof useTranslations>;

function problemText(problem: ExampleProblem, t: Translate): string {
  return problem === "too_large"
    ? t("flow_editor_tools_contract_example_too_large", {
        characters: EXAMPLE_MAX_CHARACTERS,
        fields: EXAMPLE_MAX_FIELDS
      })
    : t(`flow_editor_tools_contract_example_problem_${problem}`);
}

function shapeText(shape: ExampleShape, t: Translate): string {
  switch (shape.kind) {
    case "object":
      return shape.fields.length > 0
        ? t("flow_editor_tools_contract_example_type_object_fields", {
            fields: shape.fields.join(", ")
          })
        : t("flow_editor_tools_contract_example_type_object");
    case "list":
      return shape.item
        ? t("flow_editor_tools_contract_example_type_list", { item: shapeText(shape.item, t) })
        : t("flow_editor_tools_contract_example_type_list_any");
    default:
      return t(`flow_editor_tools_contract_example_type_${shape.kind}`);
  }
}

/**
 * "Skapa från exempel": the author pastes an answer the step should give and
 * sees the output contract it implies, field by field, with what one example
 * cannot decide. Nothing changes until the author accepts it; a contract the
 * step already has is replaced only after a confirmation.
 */
export function ContractFromExampleDialog({
  current,
  isDisabled,
  onAccept
}: {
  current: JsonObject | null;
  isDisabled?: boolean;
  onAccept: (contract: JsonObject) => void;
}) {
  const t = useTranslations();
  const notVariableId = useId();
  const [open, setOpen] = useState(false);
  const [example, setExample] = useState("");
  const [confirmReplace, setConfirmReplace] = useState(false);
  const reading = example.trim() ? contractFromExample(example) : null;
  const nonVariable = reading?.ok === true && reading.fields.some((field) => !field.variable);

  function close() {
    setOpen(false);
    setExample("");
  }

  function accept() {
    if (!reading?.ok) return;
    onAccept(reading.contract);
    setConfirmReplace(false);
    close();
  }

  return (
    <>
      <div>
        <Button
          label={t("flow_editor_tools_contract_example_button")}
          icon={<ClipboardPaste className="size-4" aria-hidden="true" />}
          size="sm"
          isDisabled={isDisabled}
          onClick={() => setOpen(true)}
        />
      </div>
      <Dialog isOpen={open} onOpenChange={(next) => (next ? setOpen(true) : close())} width={560}>
        <Layout
          height="auto"
          header={
            <DialogHeader
              title={t("flow_editor_tools_contract_example_title")}
              subtitle={t("flow_editor_tools_contract_example_description")}
              onOpenChange={(next) => (next ? setOpen(true) : close())}
            />
          }
          content={
            open ? (
              <LayoutContent>
                <div className="flex flex-col gap-4">
                  <TextArea
                    label={t("flow_editor_tools_contract_example_label")}
                    value={example}
                    onChange={setExample}
                    rows={6}
                    hasSpellCheck={false}
                    controlClassName="font-mono"
                    status={
                      reading?.ok === false
                        ? { type: "error", message: problemText(reading.problem, t) }
                        : undefined
                    }
                    width="100%"
                  />
                  {reading?.ok ? (
                    <section className="flex flex-col gap-2">
                      <Text type="label" as="h3" display="block" className="m-0">
                        {t("flow_editor_tools_contract_example_preview")}
                      </Text>
                      <ul className="border-ax-border rounded-ax-container m-0 flex max-h-[30vh] list-none flex-col overflow-y-auto border p-0">
                        {reading.fields.map((field) => (
                          <li
                            key={field.name}
                            className="border-ax-border flex flex-wrap items-baseline justify-between gap-2 border-b px-3 py-1.5 last:border-b-0"
                          >
                            <span className="flex min-w-0 items-center gap-2">
                              <code className="text-ax-text font-mono text-xs break-all">
                                {field.name}
                              </code>
                              {!field.variable ? (
                                <Token
                                  size="sm"
                                  color="red"
                                  label={t("flow_editor_tools_contract_example_not_variable")}
                                  aria-describedby={notVariableId}
                                />
                              ) : null}
                            </span>
                            <span className="text-ax-text-secondary text-xs">
                              {shapeText(field.shape, t)}
                            </span>
                          </li>
                        ))}
                      </ul>
                      {nonVariable ? (
                        <Text
                          id={notVariableId}
                          type="supporting"
                          size="sm"
                          as="p"
                          display="block"
                          className="m-0"
                        >
                          {t("flow_editor_tools_contract_example_not_variable_reason")}
                        </Text>
                      ) : null}
                      {reading.notes.map((note) => (
                        <Text
                          key={note}
                          type="supporting"
                          size="sm"
                          as="p"
                          display="block"
                          className="m-0"
                        >
                          {t(`flow_editor_tools_contract_example_note_${note}`)}
                        </Text>
                      ))}
                    </section>
                  ) : null}
                </div>
              </LayoutContent>
            ) : null
          }
          footer={
            open ? (
              <LayoutFooter>
                <div className="flex flex-wrap justify-end gap-2">
                  <Button label={t("cancel")} onClick={close} />
                  <Button
                    variant="primary"
                    label={t("flow_editor_tools_contract_example_accept")}
                    isDisabled={!reading?.ok}
                    onClick={() => {
                      if (!reading?.ok) return;
                      if (current !== null) setConfirmReplace(true);
                      else accept();
                    }}
                  />
                </div>
              </LayoutFooter>
            ) : null
          }
        />
      </Dialog>
      <ConfirmDialogControlled
        open={confirmReplace}
        onOpenChange={setConfirmReplace}
        title={t("flow_editor_tools_contract_example_replace_title")}
        description={t("flow_editor_tools_contract_example_replace_description")}
        confirmLabel={t("flow_editor_tools_contract_example_replace")}
        variant="default"
        onConfirm={accept}
      />
    </>
  );
}
