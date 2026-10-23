"use client";

import type { ChatComposerToken, ChatComposerTrigger } from "@astryxdesign/core/Chat";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { createStaticSource, type SearchableItem } from "@astryxdesign/core/Typeahead";
import { AtSign } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useState } from "react";
import type { ChatReferences, ComposerInsert } from "@/features/chat/chat-references";
import type { FlowPublic } from "../editor/step-types";
import { meaningLabel } from "../editor/step-labels";
import { stepLabel } from "../flow-labels";
import { referenceComponents, referenceRemarkPlugins } from "./answer-references";
import { ReferencePill, ReferencePillButton } from "./reference-pill";
import {
  RUN_CHOICES,
  referenceChoices,
  referencesIn,
  stepReference,
  valueOf,
  type Reference,
  type ReferenceChoice
} from "./references";

type Flow = Pick<FlowPublic, "steps" | "metadata_json">;
type ChoiceItem = SearchableItem<{ choice: ReferenceChoice; group: string }>;

/** What a menu row says: the step ("1 Extrahera"), or what the value is ("fastighet", "text"). */
function rowLabel(
  choice: ReferenceChoice,
  flow: Flow,
  t: ReturnType<typeof useTranslations>
): string {
  if (choice.kind === "run") {
    const value = valueOf(choice.token, flow);
    return value.kind === "value" ? meaningLabel(value.meaning, choice.token, flow, t) : choice.raw;
  }
  const step = `${choice.step.step_order} ${choice.step.user_description?.trim() || t("flows_step_unnamed")}`;
  if (choice.kind === "step") return step;
  const what =
    choice.what.type === "field"
      ? choice.what.field
      : choice.what.type === "text"
        ? t("flows_chat_reference_value_text")
        : t("flows_chat_reference_value_structured");
  return `${step} › ${what}`;
}

function toReference(choice: ReferenceChoice, flow: Flow): Reference {
  if (choice.kind === "step") {
    return stepReference(choice.step.id!, choice.step.user_description?.trim() || "", flow);
  }
  return valueOf(choice.token, flow);
}

/** A row of the reference menu: the pill as it will look, and what it is. */
function ReferenceRow({ choice, flow }: { choice: ReferenceChoice; flow: Flow }) {
  const t = useTranslations();
  return (
    <span className="flex min-w-0 items-center gap-2">
      <ReferencePill reference={toReference(choice, flow)} />
      <Text type="supporting" size="sm" className="truncate">
        {choice.kind === "run"
          ? t("flows_chat_reference_item_run")
          : choice.kind === "step"
            ? t("flows_chat_reference_item_step")
            : choice.what.type === "field"
              ? t("flows_chat_reference_item_field")
              : choice.what.type === "text"
                ? t("flows_chat_reference_item_text")
                : t("flows_chat_reference_item_structured")}
      </Text>
    </span>
  );
}

/**
 * The flow chat's references: typing "@" (or the "Referera" button) lists
 * every step and the values it produces, grouped by step; a pick becomes a
 * pill in the field and travels as `@[Name](step:<id>)` or `{{…}}`; the
 * same references are pills in sent questions and in answers. Render inside
 * a FlowReferencesProvider, which the pills read the flow from.
 */
export function useFlowChatReferences(flow: Flow): {
  /** For the ChatView. */
  references: ChatReferences;
  /** For FlowReferences around it: the composer on screen, or null. */
  composer: ComposerInsert | null;
} {
  const t = useTranslations();

  const items = useMemo<ChoiceItem[]>(
    () =>
      [...referenceChoices(flow), ...RUN_CHOICES].map((choice) => ({
        id: choice.raw,
        label: rowLabel(choice, flow, t),
        auxiliaryData: {
          choice,
          group:
            choice.kind === "run" ? t("flows_chat_reference_group_run") : stepLabel(choice.step, t)
        }
      })),
    [flow, t]
  );

  const triggers = useMemo<ChatComposerTrigger[]>(
    () => [
      {
        character: "@",
        searchSource: createStaticSource(items, {
          keywords: (item) => {
            const { choice } = item.auxiliaryData!;
            if (choice.kind === "run") return [choice.token];
            return [
              choice.step.user_description ?? "",
              // "steg 1", "step_1" and "1" find the step as well as its name.
              stepLabel(choice.step, t),
              `step_${choice.step.step_order}`,
              String(choice.step.step_order),
              choice.kind === "value" ? choice.token : "",
              choice.kind === "value" && choice.what.type === "field" ? choice.what.field : ""
            ].filter(Boolean);
          }
        }),
        hasMultiWordQuery: true,
        menuLabel: t("flows_chat_reference_menu"),
        emptySearchText: t("flows_chat_reference_empty"),
        loadingText: t("flows_chat_reference_searching"),
        renderItem: (item) => (
          <ReferenceRow choice={(item as ChoiceItem).auxiliaryData!.choice} flow={flow} />
        ),
        onSelect: (item) => {
          const { choice } = (item as ChoiceItem).auxiliaryData!;
          return {
            value: choice.raw,
            render: () => <ReferencePill reference={toReference(choice, flow)} />
          };
        }
      }
    ],
    [items, flow, t]
  );

  const tokens = useCallback(
    (text: string): ChatComposerToken[] =>
      referencesIn(text, flow).map((reference) => ({
        value: reference.raw,
        render: () => <ReferencePillButton reference={reference} />
      })),
    [flow]
  );

  const headerActions = useCallback(
    (input: ComposerInsert) => (
      <IconButton
        label={t("flows_chat_reference_button")}
        icon={<AtSign aria-hidden="true" />}
        variant="ghost"
        size="sm"
        onClick={() => input.insertText("@")}
      />
    ),
    [t]
  );

  // The chat's composer, for the reference card's "Infoga i meddelandet".
  const [composer, setComposer] = useState<ComposerInsert | null>(null);
  const references = useMemo<ChatReferences>(
    () => ({
      triggers,
      tokens,
      remarkPlugins: referenceRemarkPlugins,
      components: referenceComponents,
      headerActions,
      onComposer: setComposer
    }),
    [triggers, tokens, headerActions]
  );
  return { references, composer };
}
