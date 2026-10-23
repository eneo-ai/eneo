"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Text } from "@astryxdesign/core/Text";
import { ChevronDown, ChevronRight, MessageSquareText, Trash2, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useFlowReferences } from "./chat/reference-pill";
import { ReferenceText, referencePlainText } from "./chat/reference-text";
import type { FlowStep } from "./flows-api";
import { stepLabel } from "./flow-labels";
import {
  isPatchable,
  suggestionRequest,
  suggestionText,
  type FlowSuggestion
} from "./flow-suggestions";

/**
 * "Åtgärda" for suggestions whose fix is a patch: the page makes the fixes
 * named by fingerprint (one for a single suggestion, several for "Åtgärda
 * alla") on the draft revision on screen and resolves to whether they were
 * saved; a refusal is the page's to show. Absent, no "Åtgärda" is offered.
 */
export type SuggestionFix = {
  onFix: (fingerprints: string[]) => Promise<boolean>;
  /** A fix is being saved: the buttons show it and ignore another press. */
  pending: boolean;
};

/** What a suggestion offers to do, by where it is shown. */
export type SuggestionActions = {
  /** Opens the step the suggestion is about; left out where that step is already open. */
  onOpenStep?: (step: FlowStep) => void;
  /**
   * Puts a prepared request about the suggestion in the flow chat's composer
   * (never sends it); left out while the chat is not available.
   */
  onAskChat?: (text: string) => void;
  /** Makes a patch suggestion's fix; left out where fixes are not offered. */
  onFix?: (suggestion: FlowSuggestion) => void;
  fixPending?: boolean;
  /**
   * The id of a visible reason "Åtgärda" cannot be used now (the step
   * editor has unsaved changes); the button is then disabled.
   */
  fixBlockedBy?: string;
  /**
   * For a step nothing reads (`unread_result`): the step list's own removal,
   * with its confirmation and its check of what reads the step.
   */
  onRemoveStep?: (step: FlowStep) => void;
};

/**
 * Runs a fix and says how it went: announced politely, and focus moved to
 * `rescueTarget` when the fixed suggestion (and the button pressed) leaves
 * the page. A refused fix is announced by the page with its notice.
 */
export function useSuggestionFix(
  fix: SuggestionFix | undefined,
  rescueTarget: () => HTMLElement | null
): ((fingerprints: string[]) => void) | undefined {
  const t = useTranslations();
  const announce = useAnnounce();
  const rescue = useFocusRescue();
  if (!fix) return undefined;
  return (fingerprints) => {
    if (fix.pending || fingerprints.length === 0) return;
    void fix.onFix(fingerprints).then((saved) => {
      if (!saved) return;
      announce(t("flow_suggestions_fixed", { count: fingerprints.length }));
      rescue(rescueTarget);
    });
  };
}

/**
 * One suggestion, on its step's card and at the top of the step editor
 * alike: what was found (steps and values as the chat's pills), why behind a
 * disclosure, and its actions. "Fråga assistenten" is offered for every fix
 * kind, since an author may want any of them explained; "Åtgärda" for a
 * patch; "Ta bort steget" for a step nothing reads.
 */
export function FlowSuggestionItem({
  suggestion,
  step,
  steps,
  showStep = false,
  onOpenStep,
  onAskChat,
  onFix,
  fixPending = false,
  fixBlockedBy,
  onRemoveStep
}: SuggestionActions & {
  suggestion: FlowSuggestion;
  /** The step the suggestion is about; null for one about the run form. */
  step: FlowStep | null;
  /** The draft's steps, to name the others the suggestion is about. */
  steps: readonly FlowStep[];
  /** Shows the step's name above the suggestion, where steps are listed together. */
  showStep?: boolean;
}) {
  const t = useTranslations();
  const refs = useFlowReferences();
  const whyId = useId();
  const [open, setOpen] = useState(false);
  const label = step ? stepLabel(step, t) : null;
  const text = suggestionText(suggestion, t, step ?? undefined, steps);
  // The title in words, each pill as it reads, for the buttons' names.
  const title = referencePlainText(text.title, refs?.flow ?? { steps: [...steps] }, t);

  return (
    <li className="flex flex-col gap-1">
      {(showStep && label) || (onOpenStep && step) ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {showStep && label ? (
            <span className="text-ax-text text-sm font-semibold break-words">{label}</span>
          ) : null}
          {onOpenStep && step && label ? (
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
      <Text size="sm" as="p" display="block" className="m-0 leading-7">
        <ReferenceText text={text.title} />
      </Text>
      <div className="flex flex-wrap items-center gap-1">
        {/* A native disclosure: Astryx's Collapsible has no compact trigger. */}
        <Button
          label={t("flow_suggestion_why")}
          aria-label={t("flow_suggestion_why_named", { title })}
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
            aria-label={t("flow_suggestion_ask_named", { title })}
            size="sm"
            variant="ghost"
            icon={<MessageSquareText aria-hidden="true" className="size-4" />}
            onClick={() => onAskChat(suggestionRequest(suggestion, steps, t))}
          />
        ) : null}
        {onFix && isPatchable(suggestion) ? (
          <Button
            label={t("flow_suggestion_fix")}
            aria-label={t("flow_suggestion_fix_named", { title })}
            size="sm"
            icon={<Wrench aria-hidden="true" className="size-4" />}
            isLoading={fixPending}
            isInterruptible
            isDisabled={fixBlockedBy !== undefined}
            aria-describedby={fixBlockedBy}
            onClick={() => {
              if (!fixPending && !fixBlockedBy) onFix(suggestion);
            }}
          />
        ) : null}
        {onRemoveStep && step && label && suggestion.code === "unread_result" ? (
          <Button
            label={t("flow_suggestion_remove_step")}
            aria-label={t("flow_suggestion_remove_step_named", { step: label })}
            size="sm"
            variant="ghost"
            icon={<Trash2 aria-hidden="true" className="size-4" />}
            onClick={() => onRemoveStep(step)}
          />
        ) : null}
      </div>
      <div id={whyId} hidden={!open}>
        <Text type="supporting" size="sm" as="p" display="block" className="m-0 leading-7">
          <ReferenceText text={text.explanation} />
        </Text>
      </div>
    </li>
  );
}
