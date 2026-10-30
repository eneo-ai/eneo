"use client";

import { DropdownMenu, type DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Braces } from "lucide-react";
import { useTranslations } from "use-intl";
import type { FieldAnchor } from "./field-problems";
import { variableEntryLabel, variableGroupTitle } from "./step-labels";
import type { VariableGroup } from "./step-variables";

/** The status an Astryx field takes for a problem, or none. */
export function problemStatus(message: string | null | undefined) {
  return message ? ({ type: "error", message } as const) : undefined;
}

/** The id of the element that wraps the field of `anchor`, for "go to the field". */
export function anchorElementId(formId: string, anchor: FieldAnchor): string {
  return `${formId}-${anchor.replace(/\./g, "-")}`;
}

/** Moves focus to the first control inside the field of `anchor`. */
export function focusAnchor(formId: string, anchor: FieldAnchor): boolean {
  const container = document.getElementById(anchorElementId(formId, anchor));
  const control = container?.querySelector<HTMLElement>(
    "input:not([type=hidden]), textarea, select, button, [tabindex]:not([tabindex='-1'])"
  );
  if (!control) return false;
  control.focus();
  return true;
}

/** Wraps the controls of one field so a problem can point at them. */
export function Anchor({
  formId,
  anchor,
  children,
  className
}: {
  formId: string;
  anchor: FieldAnchor;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div id={anchorElementId(formId, anchor)} className={className ?? "flex flex-col gap-3"}>
      {children}
    </div>
  );
}

/** A problem shown as text under a group of controls that has no status of its own. */
export function FieldMessage({ id, message }: { id?: string; message: string | null | undefined }) {
  if (!message) return null;
  return (
    <Text id={id} as="p" display="block" type="supporting" size="sm" className="text-ax-error m-0">
      {message}
    </Text>
  );
}

/** One part of the editor: a heading (h3, under the editor's h2) and its fields. */
export function EditorSection({
  id,
  title,
  description,
  children
}: {
  id: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="border-ax-border flex flex-col gap-4 border-t pt-5">
      <div className="flex flex-col gap-1">
        <Heading level={3} id={id}>
          {title}
        </Heading>
        {description && (
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {description}
          </Text>
        )}
      </div>
      {children}
    </section>
  );
}

/** A menu of the references a step can read; choosing one inserts `{{reference}}`. */
export function VariablePicker({
  groups,
  onInsert,
  label,
  isDisabled
}: {
  groups: VariableGroup[];
  onInsert: (token: string) => void;
  label?: string;
  isDisabled?: boolean;
}) {
  const t = useTranslations();
  const items: DropdownMenuOption[] = groups.map((group) => ({
    type: "section",
    id: group.type === "step" ? `step-${group.stepOrder}` : group.type,
    title: variableGroupTitle(group, t),
    items: group.entries.map((entry) => ({
      id: entry.token,
      label: variableEntryLabel(entry, t),
      description: `{{${entry.token}}}`,
      onClick: () => onInsert(entry.token)
    }))
  }));
  return (
    <DropdownMenu
      presentation="adaptive"
      placement="below"
      alignment="start"
      menuWidth={320}
      button={{
        label: label ?? t("flow_step_editor_insert_variable"),
        variant: "secondary",
        size: "sm",
        icon: <Braces className="size-4" aria-hidden="true" />,
        isDisabled: isDisabled || groups.length === 0
      }}
      items={items}
    />
  );
}
