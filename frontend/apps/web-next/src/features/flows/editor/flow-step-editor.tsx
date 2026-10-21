"use client";

import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "next-intl";
import type { components } from "@/lib/api/schema";

type FlowPublic = components["schemas"]["FlowPublic"];

/**
 * Placeholder for the step configuration editor, which is built on its own
 * and replaces this file. The flow page mounts it where a step is opened;
 * the contract (props and export) is what the page relies on.
 */
export function FlowStepEditor(props: {
  flow: FlowPublic;
  stepId: string;
  readOnly: boolean;
  onSaved: (flow: FlowPublic) => void;
  onCancel: () => void;
}): React.JSX.Element {
  const t = useTranslations();
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-ax-text-secondary text-sm">{t("flows_step_editor_pending")}</p>
      <Button label={t("flows_step_editor_back")} onClick={props.onCancel} />
    </div>
  );
}
