import type { ChatComposerToken, ChatComposerTrigger } from "@astryxdesign/core/Chat";
import { Text } from "@astryxdesign/core/Text";
import { useTranslations } from "use-intl";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { ChatReferences, ComposerInsert } from "@/features/chat/chat-references";
import { mentionPattern, parseMention } from "@/features/references/mentions";
import {
  referenceComponents,
  referenceRemarkPlugins
} from "@/features/references/answer-references";
import {
  insertParts,
  referenceMenuTrigger,
  type InsertPart,
  type ReferenceMenuItem
} from "@/features/references/reference-menu";
import { PillButton, ReferenceToken } from "@/features/references/reference-pill";
import {
  SETTING_SCHEME,
  settingMention,
  settingParts,
  type SettingReference
} from "./setting-references";

/** What the form shows the person, by key, and how to show one of them there. */
type SettingReferencesValue = {
  references: ReadonlyMap<string, SettingReference>;
  /** Shows the setting or section in the form and moves focus to it. */
  show: (key: string) => void;
};

const SettingReferencesContext = createContext<SettingReferencesValue | null>(null);

/**
 * Gives the helper chat the assistant's settings: its pills read what the
 * form shows here, and pressing one shows the setting. Render around the
 * helper panel.
 */
export function SettingReferences({
  references,
  show,
  children
}: SettingReferencesValue & { children: ReactNode }) {
  const value = useMemo(() => ({ references, show }), [references, show]);
  return (
    <SettingReferencesContext.Provider value={value}>{children}</SettingReferencesContext.Provider>
  );
}

/** A setting as a pill, named as the editor names it now. */
function SettingPill({ reference }: { reference: Pick<SettingReference, "label"> }) {
  return <ReferenceToken color="blue" label={reference.label} />;
}

/** A pill in a message: a button that shows the setting in the form. */
function SettingPillButton({ reference }: { reference: SettingReference }) {
  const refs = useContext(SettingReferencesContext);
  return (
    <PillButton className="align-middle" onClick={() => refs?.show(reference.key)}>
      <SettingPill reference={reference} />
    </PillButton>
  );
}

/**
 * A mention as written in a message: the pill of a setting the form shows
 * this person, or, for anything it does not show, the name as plain text.
 */
function SettingMention({ name, settingKey }: { name: string; settingKey: string }) {
  const reference = useContext(SettingReferencesContext)?.references.get(settingKey);
  return reference ? <SettingPillButton reference={reference} /> : <>{name}</>;
}

/** Stable, so Streamdown keeps one processor for every answer. */
const remarkPlugins = referenceRemarkPlugins(mentionPattern(SETTING_SCHEME), [SETTING_SCHEME]);

const components = referenceComponents(function SettingInAnswer({ raw, children }) {
  const mention = parseMention(raw, SETTING_SCHEME);
  return mention ? (
    <SettingMention name={mention.name} settingKey={mention.key} />
  ) : (
    <>{children}</>
  );
});

/** A reference as the pill the composer holds; its value is the mention as written. */
function settingToken(reference: SettingReference): ChatComposerToken {
  return { value: settingMention(reference), render: () => <SettingPill reference={reference} /> };
}

/**
 * Puts a prepared message into the composer at the caret: its text as
 * typed, each mention of a setting the form shows as its pill, any other
 * mention as its name. Nothing is sent.
 */
export function insertSettingMessage(
  composer: ComposerInsert,
  text: string,
  references: ReadonlyMap<string, SettingReference>
) {
  insertParts(
    composer,
    settingParts(text).map((part): InsertPart => {
      if (part.kind === "text") return part;
      const reference = references.get(part.key);
      return reference
        ? { kind: "token", token: settingToken(reference) }
        : { kind: "text", text: part.name };
    })
  );
}

/** A row of the "@" menu: the pill as it will look, and what the setting is set to now. */
function SettingRow({ reference }: { reference: SettingReference }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <SettingPill reference={reference} />
      <Text type="supporting" size="sm" className="truncate">
        {reference.value}
      </Text>
    </span>
  );
}

/**
 * The helper chat's references to the assistant's settings: typing "@" (or
 * the "@" button) lists every section of the editor with the settings it
 * shows and their values now; a pick becomes a pill in the field and
 * travels as `@[Name](setting:<key>)`; the same mentions are pills in sent
 * messages and in answers. `references` are the form's, in its order (see
 * `settingReferences`). Render the chat inside SettingReferences.
 */
export function useSettingReferenceMenu(references: readonly SettingReference[]): {
  /** For the helper's adapter. */
  references: ChatReferences;
  /** The chat's composer while it is on screen, to put a reference into. */
  composer: ComposerInsert | null;
  /** The same references by key, for SettingReferences; kept while the list is the same. */
  byKey: ReadonlyMap<string, SettingReference>;
} {
  const t = useTranslations();
  // The list is rebuilt with the editor; the menu changes only with what it lists.
  const signature = JSON.stringify(references);
  const listed = useMemo(() => JSON.parse(signature) as SettingReference[], [signature]);
  const byKey = useMemo(
    () => new Map(listed.map((reference) => [reference.key, reference])),
    [listed]
  );

  const triggers = useMemo<ChatComposerTrigger[]>(() => {
    const items: ReferenceMenuItem<SettingReference>[] = listed.map((reference) => ({
      id: reference.key,
      label: reference.label,
      group: reference.sectionLabel,
      // The section's name finds its settings; a value finds what is set to it.
      keywords: [reference.sectionLabel, reference.value],
      value: reference
    }));
    return [
      referenceMenuTrigger({
        items,
        menuLabel: t("helper_reference_menu"),
        emptyText: t("helper_reference_empty"),
        loadingText: t("flows_chat_reference_searching"),
        renderItem: (reference) => <SettingRow reference={reference} />,
        toToken: settingToken
      })
    ];
  }, [listed, t]);

  const tokens = useCallback((text: string): ChatComposerToken[] => {
    const seen = new Set<string>();
    return settingParts(text).flatMap((part) => {
      if (part.kind === "text" || seen.has(part.raw)) return [];
      seen.add(part.raw);
      return [
        {
          value: part.raw,
          render: () => <SettingMention name={part.name} settingKey={part.key} />
        }
      ];
    });
  }, []);

  const [composer, setComposer] = useState<ComposerInsert | null>(null);
  const chatReferences = useMemo<ChatReferences>(
    () => ({ triggers, tokens, remarkPlugins, components, onComposer: setComposer }),
    [triggers, tokens]
  );
  return { references: chatReferences, composer, byKey };
}
