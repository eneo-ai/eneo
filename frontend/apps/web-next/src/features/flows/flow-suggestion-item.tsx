"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { ListItem } from "@astryxdesign/core/List";
import { Text } from "@astryxdesign/core/Text";
import { ChevronDown, ChevronRight, MessageSquareText, Trash2, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useFlowReferences } from "./chat/reference-pill";
import { ReferenceText, referencePlainText } from "./chat/reference-text";
import type { FlowStep } from "./flows-api";
import { stepLabel } from "./flow-labels";
import {
  isPatchable,
  measuredImpactText,
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

const LEVEL_BADGES = {
  high: {
    variant: "info",
    label: "flow_suggestion_level_high",
    named: "flow_suggestion_level_high_named"
  },
  medium: {
    variant: "neutral",
    label: "flow_suggestion_level_medium",
    named: "flow_suggestion_level_medium_named"
  },
  low: {
    variant: "neutral",
    label: "flow_suggestion_level_low",
    named: "flow_suggestion_level_low_named"
  }
} as const;

/** How much a suggestion is worth, in a word: the badge says it, its colour only repeats it. */
function LevelBadge({ level }: { level: string }) {
  const t = useTranslations();
  const badge = LEVEL_BADGES[level as keyof typeof LEVEL_BADGES];
  if (!badge) return null;
  return (
    <Badge
      variant={badge.variant}
      label={
        <>
          <span aria-hidden="true">{t(badge.label)}</span>
          <span className="sr-only">{t(badge.named)}</span>
        </>
      }
    />
  );
}

/**
 * One suggestion as a row of a suggestion list: its level, what was found
 * (steps and values as the chat's pills), for a measured one what the runs
 * measured (always in view) and, for a patch, "Åtgärda" on the right. The
 * chevron before it shows why, with the secondary actions:
 * "Fråga assistenten" for every kind (an author may want any of them
 * explained) and "Ta bort steget" for a step nothing reads. Collapsing
 * keeps focus on the chevron, which stays.
 */
export function SuggestionRow({
  suggestion,
  step,
  steps,
  isOpen,
  onOpenChange,
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
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const refs = useFlowReferences();
  const panelId = useId();
  const label = step ? stepLabel(step, t) : null;
  const text = suggestionText(suggestion, t, step ?? undefined, steps);
  const measured = measuredImpactText(suggestion.impact, t);
  // The title in words, each pill as it reads, for the buttons' names.
  const title = referencePlainText(text.title, refs?.flow ?? { steps: [...steps] }, t);
  const removable = onRemoveStep && step && label && suggestion.code === "unread_result";

  return (
    <ListItem
      align="first-line"
      startContent={
        <IconButton
          label={t("flow_suggestion_more_named", { title })}
          aria-expanded={isOpen}
          aria-controls={panelId}
          icon={isOpen ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
          variant="ghost"
          size="sm"
          onClick={() => onOpenChange(!isOpen)}
        />
      }
      label={
        <div className="flex min-w-0 flex-col gap-1 py-0.5">
          <p className="text-ax-text m-0 text-sm leading-6">
            <span className="mr-2 inline-block align-middle">
              <LevelBadge level={suggestion.impact.level} />
            </span>
            <ReferenceText text={text.title} />
          </p>
          {measured ? (
            <Text type="supporting" size="sm" as="p" display="block" className="m-0 leading-6">
              {measured}
            </Text>
          ) : null}
          <div id={panelId} hidden={!isOpen} className="flex flex-col gap-1">
            <Text type="supporting" size="sm" as="p" display="block" className="m-0 leading-6">
              <ReferenceText text={text.explanation} />
            </Text>
            {onAskChat || removable ? (
              <div className="-ml-2 flex flex-wrap items-center gap-1">
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
                {removable ? (
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
            ) : null}
          </div>
        </div>
      }
      endContent={
        onFix && isPatchable(suggestion) ? (
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
        ) : undefined
      }
    />
  );
}
