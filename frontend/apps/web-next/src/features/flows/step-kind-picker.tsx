"use client";

import { DropdownMenu, type DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import {
  AudioLines,
  Braces,
  FileText,
  FunctionSquare,
  Plus,
  Sparkles,
  TextQuote,
  User
} from "lucide-react";
import { useTranslations } from "next-intl";
import { stepKindLabel } from "./flow-labels";
import type { StepKind } from "./types";

/** The kinds a person can add by hand, in the order the picker lists them. */
export const STEP_KINDS: StepKind[] = [
  "llm",
  "compose",
  "document",
  "review",
  "transcribe",
  "function"
];

const KIND_ICONS: Record<StepKind, React.ReactNode> = {
  llm: <Sparkles className="size-4" />,
  compose: <TextQuote className="size-4" />,
  document: <FileText className="size-4" />,
  review: <User className="size-4" />,
  transcribe: <AudioLines className="size-4" />,
  function: <FunctionSquare className="size-4" />
};

export const KIND_DESCRIPTION_KEYS: Record<StepKind, string> = {
  llm: "flow_kind_llm_description",
  compose: "flow_kind_compose_description",
  document: "flow_kind_document_description",
  review: "flow_kind_review_description",
  transcribe: "flow_kind_transcribe_description",
  function: "flow_kind_function_description"
};

/** The glyph of a step kind, as the picker and the overview show it. */
export function kindIcon(kind: StepKind) {
  return KIND_ICONS[kind] ?? <Braces className="size-4" />;
}

/**
 * "Lägg till steg": a menu of the six step kinds with one line on each.
 * Picking one opens the editor with a blank step of that kind at the
 * position the trigger stands for.
 */
export function StepKindPicker({
  label,
  onPick,
  iconOnly = false
}: {
  /** The trigger's accessible name ("Infoga steg efter 2", "Lägg till steg sist"). */
  label: string;
  onPick: (kind: StepKind) => void;
  /** A small plus button on the rail, instead of a labelled button. */
  iconOnly?: boolean;
}) {
  const t = useTranslations();
  const items: DropdownMenuOption[] = STEP_KINDS.map((kind) => ({
    id: kind,
    label: stepKindLabel(kind, t),
    description: t(KIND_DESCRIPTION_KEYS[kind]),
    icon: kindIcon(kind),
    onClick: () => onPick(kind)
  }));
  return (
    <DropdownMenu
      button={{
        label,
        icon: <Plus className="size-4" />,
        isIconOnly: iconOnly,
        variant: iconOnly ? "ghost" : "secondary",
        size: "sm",
        tooltip: iconOnly ? label : undefined
      }}
      items={items}
      hasChevron={!iconOnly}
      menuWidth={360}
      presentation="adaptive"
    />
  );
}
