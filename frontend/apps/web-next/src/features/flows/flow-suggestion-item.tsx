"use client";

import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { ChevronDown, ChevronRight, MessageSquareText } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import type { FlowStep } from "./flows-api";
import { stepLabel } from "./flow-labels";
import { suggestionRequest, suggestionText, type FlowSuggestion } from "./flow-suggestions";

/** What a suggestion offers to do, by where it is shown. */
export type SuggestionActions = {
  /** Opens the step the suggestion is about; left out where that step is already open. */
  onOpenStep?: (step: FlowStep) => void;
  /**
   * Puts a prepared request about the suggestion in the flow chat's composer
   * (never sends it); left out while the chat is not available.
   */
  onAskChat?: (text: string) => void;
};

/**
 * One suggestion, in the draft check's "Förslag" and at the top of the step
 * editor alike: the step it is about (where several steps are listed), what
 * was found, why behind a disclosure, and its actions. "Fråga assistenten" is
 * offered for every fix kind, since an author may want any of them explained.
 */
export function FlowSuggestionItem({
  suggestion,
  step,
  steps,
  showStep,
  onOpenStep,
  onAskChat
}: SuggestionActions & {
  suggestion: FlowSuggestion;
  /** The step the suggestion is about. */
  step: FlowStep;
  /** The draft's steps, to name the others the suggestion is about. */
  steps: readonly FlowStep[];
  showStep: boolean;
}) {
  const t = useTranslations();
  const whyId = useId();
  const [open, setOpen] = useState(false);
  const label = stepLabel(step, t);
  const text = suggestionText(suggestion, t, step);

  return (
    <li className="flex flex-col gap-1">
      {showStep || onOpenStep ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {showStep ? (
            <span className="text-ax-text text-sm font-semibold break-words">{label}</span>
          ) : null}
          {onOpenStep ? (
            <Button
              label={t("flow_editor_tools_check_open_step")}
              aria-label={t("flow_editor_tools_check_open_step_named", { step: label })}
              size="sm"
              variant="ghost"
              onClick={() => onOpenStep(step)}
            />
          ) : null}
        </div>
      ) : null}
      <Text size="sm" as="p" display="block" className="m-0">
        {text.title}
      </Text>
      <div className="flex flex-wrap items-center gap-1">
        {/* A native disclosure: Astryx's Collapsible has no compact trigger. */}
        <Button
          label={t("flow_suggestion_why")}
          aria-label={t("flow_suggestion_why_named", { title: text.title })}
          aria-expanded={open}
          aria-controls={whyId}
          size="sm"
          variant="ghost"
          icon={
            open ? (
              <ChevronDown aria-hidden="true" className="size-4" />
            ) : (
              <ChevronRight aria-hidden="true" className="size-4" />
            )
          }
          onClick={() => setOpen((current) => !current)}
        />
        {onAskChat ? (
          <Button
            label={t("flow_suggestion_ask")}
            aria-label={t("flow_suggestion_ask_named", { title: text.title, step: label })}
            size="sm"
            variant="ghost"
            icon={<MessageSquareText aria-hidden="true" className="size-4" />}
            onClick={() => onAskChat(suggestionRequest(suggestion, steps, t))}
          />
        ) : null}
      </div>
      <div id={whyId} hidden={!open}>
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {text.explanation}
        </Text>
      </div>
    </li>
  );
}
