"use client";

import { AtSign, Code } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { parseInstructionReferences, type ReferenceCatalog } from "@eneo/skill-instructions";
import {
  createInstructionEditor,
  type InstructionEditor,
  type ReferenceSelection
} from "@eneo/skill-instructions/editor";
import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { useTranslations } from "next-intl";
import { SkillReferencePicker } from "./skill-reference-picker";
import "@eneo/skill-instructions/editor.css";

export function SkillInstructionEditor({
  value,
  onChange,
  id,
  describedBy = "",
  disabled,
  invalid,
  catalog,
  inlinePicker = false,
  ref
}: {
  value: string;
  onChange: (value: string) => void;
  id: string;
  describedBy?: string;
  disabled: boolean;
  invalid: boolean;
  catalog: ReferenceCatalog;
  inlinePicker?: boolean;
  ref?: Ref<{ focus: () => void }>;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const mount = useRef<HTMLDivElement>(null);
  const editor = useRef<InstructionEditor | null>(null);
  const [initialValue] = useState(value);
  const [source, setSource] = useState(false);
  const [selection, setSelection] = useState<ReferenceSelection | null>(null);
  const label = t("skills_instructions_label");
  const placeholder = t("skills_reference_placeholder");
  const skillTypeLabel = t("skills_reference_kind_skill");
  const functionTypeLabel = t("skills_reference_kind_function");
  const mcpTypeLabel = t("skills_reference_kind_mcp");
  const toolTypeLabel = t("skills_reference_kind_tool");
  let malformed = false;
  try {
    parseInstructionReferences(value);
  } catch {
    malformed = true;
  }
  useImperativeHandle(ref, () => ({ focus: () => editor.current?.focus() }), []);

  useEffect(() => {
    if (!mount.current) return;
    editor.current = createInstructionEditor({
      element: mount.current,
      value: initialValue,
      id,
      label,
      placeholder,
      describedBy: `${id}-reference-hint ${id}-reference-error ${describedBy}`.trim(),
      referenceTypeLabels: {
        skill: skillTypeLabel,
        function: functionTypeLabel,
        mcp_server: mcpTypeLabel,
        mcp_tool: toolTypeLabel
      },
      editorClass:
        "text-ax-text relative min-h-48 max-h-[50dvh] overflow-y-auto px-3 py-3 text-base sm:text-sm leading-7 whitespace-pre-wrap wrap-anywhere focus-visible:outline-2 focus-visible:outline-ax-focus focus-visible:-outline-offset-2 [--skill-placeholder:var(--color-text-secondary)] [&>p]:m-0",
      referenceClass:
        "bg-ax-blue-muted text-ax-blue rounded-ax-element mx-0.5 cursor-pointer border-0 px-1.5 py-0.5 text-sm font-medium leading-normal hover:underline underline-offset-2 [&.ProseMirror-selectednode]:outline [&.ProseMirror-selectednode]:outline-ax-focus",
      onChange,
      onReference: setSelection
    });
    return () => {
      editor.current?.destroy();
      editor.current = null;
    };
  }, [
    initialValue,
    id,
    describedBy,
    label,
    onChange,
    placeholder,
    skillTypeLabel,
    functionTypeLabel,
    mcpTypeLabel,
    toolTypeLabel
  ]);
  useEffect(() => editor.current?.setValue(value), [value]);
  useEffect(
    () => editor.current?.setState({ disabled, invalid: invalid || malformed }),
    [disabled, invalid, malformed]
  );

  function closePicker() {
    setSelection(null);
    requestAnimationFrame(() => editor.current?.focus());
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="border-ax-border-control bg-ax-background rounded-ax-element overflow-hidden border">
        <div ref={mount} />
        <div className="border-ax-border flex flex-wrap items-center justify-between gap-2 border-t p-1.5">
          <Button
            label={t("skills_reference_insert")}
            icon={<AtSign />}
            size="sm"
            variant="ghost"
            isDisabled={disabled}
            onClick={() => editor.current?.openReference()}
          />
          <Button
            label={t(source ? "skills_reference_visual" : "skills_reference_source")}
            icon={<Code />}
            size="sm"
            variant="ghost"
            aria-pressed={source}
            isDisabled={disabled}
            onClick={() => {
              editor.current?.setSource(!source);
              setSource(!source);
            }}
          />
        </div>
      </div>
      <p id={`${id}-reference-hint`} className="text-ax-text-secondary text-xs leading-5">
        {t("skills_reference_hint")}
      </p>
      {malformed && (
        <p id={`${id}-reference-error`} className="text-ax-error text-sm">
          {t("skills_reference_invalid")}
        </p>
      )}
      {selection && (
        <SkillReferencePicker
          catalog={catalog}
          selection={selection}
          inline={inlinePicker}
          onClose={closePicker}
          onSelect={(candidate) => {
            const inserted = editor.current?.replace(selection, candidate.label, candidate.target);
            closePicker();
            if (inserted) announce(t("skills_reference_inserted"));
          }}
          onRemove={() => {
            editor.current?.remove(selection);
            closePicker();
          }}
        />
      )}
    </div>
  );
}
