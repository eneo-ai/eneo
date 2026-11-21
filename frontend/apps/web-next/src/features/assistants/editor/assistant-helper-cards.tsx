import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Lightbulb, PencilLine, Send } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { Fragment, useId, useRef, useState, type ReactNode } from "react";
import { Collapsible } from "@/components/astryx/collapsible";
import { SuccessMark } from "@/components/composites/success-mark";
import { useFocusRescue } from "@/lib/focus-rescue";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useCopy } from "@/lib/hooks/use-copy";
import { cn } from "@/lib/utils";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import { availableDocumentTemplatesQueryOptions } from "@/features/document-templates/document-templates";
import {
  FieldBeforeAfter,
  FOLDED_LINES,
  FoldButton,
  HELPER_CARD_COLLAPSIBLE_CLASS,
  HelperCardFrame,
  isLongText
} from "@/features/helper/helper-card";
import { editorSummaries } from "@/features/spaces/editor-summaries";
import { useSpace } from "@/features/spaces/use-space";
import { selectableRerankModels, spaceModelsQueryOptions } from "./assistant-editor-rules";
import {
  FUNCTION_FIELD_PREFIX,
  LIST_FIELDS,
  changeOf,
  changeState,
  functionName,
  kwargOf,
  listEntries,
  proposalOf,
  proposalUsed,
  publishedBy,
  requestGate,
  settingInRequest,
  toolEntries,
  type AssistantChange,
  type AssistantProposal,
  type GateContext,
  type ListEntry,
  type RequestGate,
  type SettingChange,
  type ToolEntry
} from "./assistant-helper-changes";
import {
  fieldsChangedBetween,
  useAssistantHelperForm,
  type ChangeOrigin
} from "./assistant-helper-form";
import { modelKwargLabel, modelKwargOptionLabel } from "./model-kwargs";
import { assistantQueryOptions, useUpdateAssistant, type AssistantUpdate } from "./use-assistant";

type Translate = ReturnType<typeof useTranslations>;
type Format = ReturnType<typeof useFormatter>;

/** The settings' names as the editor's fields call them. */
const SETTING_LABEL_KEYS: Record<string, string> = {
  name: "name",
  description: "description",
  prompt: "prompt",
  completion_model: "completion_model",
  knowledge_mode: "material_knowledge_timing",
  inline_file_text: "material_chat_uploads",
  groups: "collections",
  websites: "websites",
  integration_knowledge_list: "integrations",
  rerank_model_id: "material_reranker",
  mcp_servers: "mcp_servers",
  mcp_tools: "tools",
  enabled_capabilities: "capabilities",
  document_template: "document_template_choice_label",
  data_retention_days: "conversation_retention_title",
  insight_enabled: "insights",
  published: "status"
};

/** A setting's name as the editor calls it; one it does not show by its own name. */
export function settingLabel(field: string, t: Translate): string {
  const kwarg = kwargOf(field);
  if (kwarg) return modelKwargLabel(kwarg, t);
  if (field.startsWith(FUNCTION_FIELD_PREFIX)) {
    return functionName(field.slice(FUNCTION_FIELD_PREFIX.length), t);
  }
  const key = SETTING_LABEL_KEYS[field];
  return key ? t(key) : field;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** An entry of a list setting by name: a function as the editor names it. */
function entryName(field: string, entry: ListEntry, t: Translate): string {
  if (field === "enabled_capabilities") return functionName(entry.id, t);
  return entry.name ?? t("helper_card_unnamed");
}

/** A tool setting in words: on, off, or back to its server's own setting. */
function toolStateText(entry: ToolEntry | undefined, t: Translate): string {
  if (!entry) return t("helper_card_tool_server_setting");
  return t(entry.isEnabled ? "helper_card_tool_on" : "helper_card_tool_off");
}

/**
 * A setting's value in the editor's words: a model by name, a choice by its
 * option's name, retention as the editor summarises it, a switch as on or
 * off. Lists and tool settings are told as their own rows (`ListRow`,
 * `ToolsRow`).
 */
export function settingText(field: string, value: unknown, t: Translate, format: Format): string {
  if (field === "completion_model") {
    return isRecord(value) && typeof value.name === "string"
      ? value.name
      : t("helper_card_no_model");
  }
  if (field === "rerank_model_id") {
    if (!isRecord(value)) return t("material_reranker_none");
    return typeof value.name === "string" && value.name
      ? value.name
      : t("material_reranker_missing");
  }
  if (field === "document_template") {
    const mode = isRecord(value) ? value.mode : "default";
    if (mode === "builtin") return t("document_template_builtin_name");
    if (mode === "selected") {
      return isRecord(value) && typeof value.name === "string" && value.name
        ? value.name
        : t("document_template_choice_selected");
    }
    return t("document_template_choice_default");
  }
  if (field === "data_retention_days" && (value === null || typeof value === "number")) {
    return editorSummaries(t).retention(value);
  }
  if (field === "insight_enabled" && typeof value === "boolean") {
    return t(value ? "enabled" : "disabled");
  }
  if (field === "published" && typeof value === "boolean") {
    return editorSummaries(t).publishing(value);
  }
  if (field.startsWith("completion_model_kwargs.")) {
    if (value === null || value === undefined) return t("default_behavior");
    if (typeof value === "number") return format.number(value);
    if (typeof value === "string") return modelKwargOptionLabel(value, t);
  }
  if (field === "knowledge_mode" && (value === "tool" || value === "inject")) {
    return t(value === "tool" ? "material_when_needed" : "material_before_each_answer");
  }
  if (field === "inline_file_text" && typeof value === "boolean") {
    return t(value ? "material_read_directly" : "material_open_when_needed");
  }
  if (value === null || value === undefined || value === "") return t("flows_change_card_empty");
  if (typeof value === "string") return value;
  if (typeof value === "boolean") {
    return t(value ? "flows_change_card_yes" : "flows_change_card_no");
  }
  if (typeof value === "number") return format.number(value);
  return JSON.stringify(value);
}

/** "Kopiera": the text to the clipboard, confirmed at the button. */
function CopyButton({ text }: { text: string }) {
  const t = useTranslations();
  const { copy, isCopied } = useCopy();
  return (
    <Button
      size="sm"
      variant="ghost"
      label={isCopied ? t("copied") : t("copy")}
      icon={
        isCopied ? (
          <Check aria-hidden="true" className="size-4" />
        ) : (
          <Copy aria-hidden="true" className="size-4" />
        )
      }
      onClick={() => void copy(text)}
    />
  );
}

/** A text too long for the call's data, under its name: said, not shown. */
function TooLongRow({ change, copyText }: { change: SettingChange; copyText: string | null }) {
  const t = useTranslations();
  return (
    <li className="flex flex-col gap-1">
      <p className="text-ax-text-secondary m-0 text-xs font-semibold">
        {settingLabel(change.field, t)}
      </p>
      <p className="text-ax-text-secondary m-0 text-[13px]">{t("helper_card_too_long")}</p>
      {copyText !== null ? (
        <div>
          <CopyButton text={copyText} />
        </div>
      ) : null}
    </li>
  );
}

/**
 * The instructions: the new text in a block of its own, folded to a few
 * lines until "Visa hela", with the earlier text behind a disclosure and,
 * on a proposal, "Kopiera".
 */
function InstructionsRow({ change, copyText }: { change: SettingChange; copyText: string | null }) {
  const t = useTranslations();
  const format = useFormatter();
  const [open, setOpen] = useState(false);
  const after = settingText(change.field, change.after, t, format);
  const before = settingText(change.field, change.before, t, format);
  const long = isLongText(after);
  return (
    <li className="flex flex-col gap-1.5">
      <p className="text-ax-text-secondary m-0 text-xs font-semibold">
        {settingLabel(change.field, t)}
      </p>
      <div
        className={cn(
          "bg-ax-surface border-ax-border rounded-ax-element text-ax-text border px-3 py-2 text-[13px] break-words whitespace-pre-wrap",
          long && !open && "line-clamp-6"
        )}
      >
        {after}
      </div>
      {long || copyText !== null ? (
        <div className="flex flex-wrap items-center gap-1">
          {long ? <FoldButton open={open} onToggle={() => setOpen((value) => !value)} /> : null}
          {copyText !== null ? <CopyButton text={copyText} /> : null}
        </div>
      ) : null}
      <div className={HELPER_CARD_COLLAPSIBLE_CLASS}>
        <Collapsible trigger={t("helper_card_earlier_text")} chevronPosition="start">
          <p className="text-ax-text-secondary m-0 pb-1 text-[13px] break-words whitespace-pre-wrap">
            {before}
          </p>
        </Collapsible>
      </div>
    </li>
  );
}

/** A value as text, folded to a few lines until "Visa hela". */
function FoldedText({ text, folded }: { text: string; folded: boolean }) {
  return <span className={folded ? "line-clamp-4" : undefined}>{text}</span>;
}

/**
 * A setting told in terms, each a word and what it covers ("Läggs till":
 * names), never by colour alone. Many terms, or a long one, fold to a few
 * until "Visa hela".
 */
function TermsRow({
  label,
  terms
}: {
  label: string;
  terms: { key: string; term: string; text: string }[];
}) {
  const [open, setOpen] = useState(false);
  const long = terms.length > FOLDED_LINES || terms.some((item) => isLongText(item.text));
  const folded = long && !open;
  const shown = folded ? terms.slice(0, FOLDED_LINES) : terms;
  return (
    <li className="flex flex-col gap-1">
      <p className="text-ax-text-secondary m-0 text-xs font-semibold">{label}</p>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
        {shown.map((item) => (
          <Fragment key={item.key}>
            <dt className="text-ax-text-secondary">{item.term}</dt>
            <dd className="text-ax-text m-0 min-w-0 break-words whitespace-pre-wrap">
              <FoldedText text={item.text} folded={folded} />
            </dd>
          </Fragment>
        ))}
      </dl>
      {long ? (
        <div>
          <FoldButton open={open} onToggle={() => setOpen((value) => !value)} />
        </div>
      ) : null}
    </li>
  );
}

/** A list setting: what is added and what is removed, by name. */
function ListRow({ change, proposal }: { change: SettingChange; proposal: boolean }) {
  const t = useTranslations();
  const format = useFormatter();
  const before = listEntries(change.before);
  const after = listEntries(change.after);
  const had = new Set(before.map((entry) => entry.id));
  const has = new Set(after.map((entry) => entry.id));
  const names = (entries: ListEntry[]) =>
    format.list(entries.map((entry) => entryName(change.field, entry, t)));
  const added = after.filter((entry) => !had.has(entry.id));
  const removed = before.filter((entry) => !has.has(entry.id));
  const terms = [
    ...(added.length > 0
      ? [
          {
            key: "added",
            term: t(proposal ? "helper_card_adds" : "helper_card_added"),
            text: names(added)
          }
        ]
      : []),
    ...(removed.length > 0
      ? [
          {
            key: "removed",
            term: t(proposal ? "helper_card_removes" : "helper_card_removed"),
            text: names(removed)
          }
        ]
      : [])
  ];
  return <TermsRow label={settingLabel(change.field, t)} terms={terms} />;
}

/** The tool settings: each tool whose setting changes, by name, and what it is set to. */
function ToolsRow({ change }: { change: SettingChange }) {
  const t = useTranslations();
  const before = new Map(toolEntries(change.before).map((entry) => [entry.id, entry]));
  const after = new Map(toolEntries(change.after).map((entry) => [entry.id, entry]));
  const terms = [...new Set([...after.keys(), ...before.keys()])].flatMap((id) => {
    const now = after.get(id);
    const then = before.get(id);
    if (now && then && now.isEnabled === then.isEnabled) return [];
    return [
      {
        key: id,
        term: now?.name ?? then?.name ?? t("helper_card_unnamed_tool"),
        text: toolStateText(now, t)
      }
    ];
  });
  return <TermsRow label={settingLabel(change.field, t)} terms={terms} />;
}

/** One setting, before and after, in the editor's words. */
function SettingRow({ change }: { change: SettingChange }) {
  const t = useTranslations();
  const format = useFormatter();
  const before = settingText(change.field, change.before, t, format);
  const after = settingText(change.field, change.after, t, format);
  return (
    <FieldBeforeAfter
      label={settingLabel(change.field, t)}
      long={isLongText(before) || isLongText(after)}
      before={(folded) => <FoldedText text={before} folded={folded} />}
      after={(folded) => <FoldedText text={after} folded={folded} />}
    />
  );
}

/**
 * The settings a card is about, one row each; `copyPrompt` offers the new
 * instructions to copy. A list says what a proposal adds and removes
 * (`proposal`), or what a change added and removed.
 */
function ChangeRows({
  changes,
  copyPrompt = null,
  proposal = false
}: {
  changes: SettingChange[];
  copyPrompt?: string | null;
  proposal?: boolean;
}) {
  return (
    <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
      {changes.map((change) => {
        const copyText = change.field === "prompt" ? copyPrompt : null;
        if (change.tooLong) {
          return <TooLongRow key={change.field} change={change} copyText={copyText} />;
        }
        if (change.field === "prompt") {
          return <InstructionsRow key={change.field} change={change} copyText={copyText} />;
        }
        if (LIST_FIELDS.has(change.field)) {
          return <ListRow key={change.field} change={change} proposal={proposal} />;
        }
        if (change.field === "mcp_tools") {
          return <ToolsRow key={change.field} change={change} />;
        }
        return <SettingRow key={change.field} change={change} />;
      })}
    </ul>
  );
}

/**
 * What a card's gate reads beyond the assistant: the space, and the ranking
 * models and templates the editor offers, read (from the editor's own
 * cache where it has them) only for a request that chooses one.
 */
function useGateContext(body: AssistantUpdate | null): GateContext {
  const { space, can } = useSpace();
  const models = useQuery({
    ...spaceModelsQueryOptions(browserApi, space.id),
    enabled: typeof body?.rerank_model_id === "string"
  });
  const templates = useQuery({
    ...availableDocumentTemplatesQueryOptions(browserApi),
    enabled: body?.document_template?.mode === "selected"
  });
  return {
    space,
    canEditSpace: can("edit", "space"),
    rerankModels: models.data ? selectableRerankModels(models.data) : undefined,
    templates: templates.data?.items
  };
}

/**
 * Saves a request as the person's own edit through the assistant's normal
 * update, so the editor's cache takes the new values. In the editor, what
 * the form has not saved goes first, so the two saves cannot race; if that
 * fails, nothing is sent and the card says so (the form shows the failure
 * as its own). Success is announced politely, naming the settings that
 * changed, which the form marks; the button that went with it hands focus
 * to the card's state (`stateId`). A failure is said at the card and in a
 * toast, and the card stays usable.
 */
function useCardSave(
  assistantId: string,
  { done, failed, origin }: { done: string; failed: string; origin: ChangeOrigin }
) {
  const t = useTranslations();
  const announce = useAnnounce();
  const rescue = useFocusRescue();
  const queryClient = useQueryClient();
  const form = useAssistantHelperForm();
  const stateId = useId();
  const save = useUpdateAssistant(assistantId);
  const [failure, setFailure] = useState<string | null>(null);
  const [savingForm, setSavingForm] = useState(false);
  // A second press while the save is on its way is the same press.
  const busy = useRef(false);
  async function send(body: AssistantUpdate, fields: readonly string[]) {
    if (busy.current) return;
    busy.current = true;
    rescue(() => document.getElementById(stateId));
    setFailure(null);
    try {
      if (form) {
        setSavingForm(true);
        const saved = await form.savePending().finally(() => setSavingForm(false));
        if (!saved) {
          setFailure(t("helper_card_held"));
          announce(t("helper_card_held"));
          return;
        }
      }
      const before = queryClient.getQueryData(
        assistantQueryOptions(browserApi, assistantId).queryKey
      );
      const after = await save.mutateAsync(body);
      const changed = before ? fieldsChangedBetween(fields, before, after) : [];
      if (form && changed.length > 0) form.showChanges(changed, origin);
      else announce(done);
    } catch (error) {
      setFailure(getErrorMessage(error, t));
      toastApiError(error, t, { title: failed });
    } finally {
      busy.current = false;
    }
  }
  return { send, pending: savingForm || save.isPending, failure, stateId };
}

/**
 * A card's action ("Använd", "Ångra"): absent where the person may not
 * make the change, disabled with its reason in words where the editor's own
 * control would be, and the failure of the last try under it.
 */
function CardAction({
  gate,
  label,
  variant,
  pending,
  failure,
  onAction
}: {
  gate: RequestGate;
  label: string;
  variant: "primary" | "secondary";
  pending: boolean;
  failure: string | null;
  onAction: () => void;
}) {
  const reasonId = useId();
  if (!gate.offered) return null;
  const reason = gate.disabledReason;
  return (
    <div className="flex flex-col items-start gap-1.5">
      <Button
        size="sm"
        variant={variant}
        label={label}
        isLoading={pending}
        isInterruptible
        isDisabled={reason !== null}
        aria-describedby={reason !== null ? reasonId : undefined}
        onClick={onAction}
      />
      {reason !== null ? (
        <p id={reasonId} className="text-ax-text-secondary m-0 text-[13px]">
          {reason}
        </p>
      ) : null}
      {failure !== null ? <p className="text-ax-error m-0 text-[13px]">{failure}</p> : null}
    </div>
  );
}

/**
 * A state of a card in words, with the success mark where the change landed.
 * It takes focus from the button that went when the state came.
 */
function CardState({ id, text, success = false }: { id: string; text: string; success?: boolean }) {
  return (
    <p
      id={id}
      tabIndex={-1}
      className="text-ax-text-secondary focus-visible:outline-ring rounded-ax-inner m-0 flex items-center gap-2 text-[13px] focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      {success ? <SuccessMark size="sm" /> : null}
      {text}
    </p>
  );
}

/**
 * A proposal of the helper chat ("Inte sparat"): each setting it would
 * change, before and after, and "Använd", which saves it as the person's
 * own edit. Whether it is in use is read from the assistant as the editor
 * has it now, so a reload or a later edit never leaves it claiming
 * otherwise; one in use shows so and offers nothing.
 */
function AssistantProposalCard({
  proposal,
  assistantId
}: {
  proposal: AssistantProposal;
  assistantId: string;
}) {
  const t = useTranslations();
  const gateContext = useGateContext(proposal.update);
  const assistant = useQuery(assistantQueryOptions(browserApi, assistantId)).data;
  const { send, pending, failure, stateId } = useCardSave(assistantId, {
    done: t("helper_card_applied"),
    failed: t("helper_card_apply_failed"),
    origin: "applied"
  });
  const used = assistant ? proposalUsed(proposal, assistant) : false;
  const gate: RequestGate = assistant
    ? requestGate(proposal.update, proposal.changes, assistant, gateContext, t)
    : { offered: false };
  const prompt = settingInRequest(proposal.update, "prompt");
  return (
    <HelperCardFrame
      label={t("helper_proposal_title", { count: proposal.changes.length })}
      icon={<Lightbulb className="size-4" />}
      status={used ? null : <Badge variant="neutral" label={t("helper_proposal_unsaved")} />}
    >
      <ChangeRows
        changes={proposal.changes}
        copyPrompt={typeof prompt === "string" ? prompt : null}
        proposal
      />
      {used ? (
        <CardState id={stateId} text={t("helper_proposal_used")} success />
      ) : (
        <CardAction
          gate={gate}
          label={t("helper_proposal_apply")}
          variant="primary"
          pending={pending}
          failure={failure}
          onAction={() =>
            void send(
              proposal.update,
              proposal.changes.map((item) => item.field)
            )
          }
        />
      )}
    </HelperCardFrame>
  );
}

/**
 * A direct change by the helper chat, which a conversation's history can
 * hold: each setting before and after,
 * and "Ångra", which saves the values from before as the person's own edit.
 * "Ångra" is offered only while the settings still have what the change
 * gave them, read from the assistant as the editor has it now; otherwise
 * the card says the change is undone or has been changed since.
 */
function AssistantChangeCard({
  change,
  assistantId
}: {
  change: AssistantChange;
  assistantId: string;
}) {
  const t = useTranslations();
  const gateContext = useGateContext(change.undo);
  const assistant = useQuery(assistantQueryOptions(browserApi, assistantId)).data;
  const { send, pending, failure, stateId } = useCardSave(assistantId, {
    done: t("helper_card_undone"),
    failed: t("helper_card_undo_failed"),
    origin: "undone"
  });
  const state = assistant ? changeState(change, assistant) : null;
  const undo = change.undo;
  let footer: ReactNode = null;
  if (state === "current" && assistant && undo) {
    footer = (
      <CardAction
        gate={requestGate(undo, change.changes, assistant, gateContext, t)}
        label={t("helper_change_undo")}
        variant="secondary"
        pending={pending}
        failure={failure}
        onAction={() =>
          void send(
            undo,
            change.changes.map((item) => item.field)
          )
        }
      />
    );
  } else if (state === "undone") {
    footer = <CardState id={stateId} text={t("helper_change_undone")} />;
  } else if (state === "changed") {
    footer = (
      <CardState
        id={stateId}
        text={t("helper_change_changed_since", { count: change.changes.length })}
      />
    );
  } else if (state === "permanent") {
    footer = <CardState id={stateId} text={t("helper_change_cannot_undo")} />;
  }
  return (
    <HelperCardFrame
      label={t("helper_change_title", { count: change.changes.length })}
      icon={<PencilLine className="size-4" />}
    >
      <ChangeRows changes={change.changes} />
      {footer}
    </HelperCardFrame>
  );
}

/**
 * The helper chat published or unpublished the assistant, with the
 * person's approval: the status before and after. A publish has no undo
 * here; the card says so and where it is done.
 */
function AssistantPublishCard({
  change,
  published
}: {
  change: AssistantChange;
  published: boolean;
}) {
  const t = useTranslations();
  return (
    <HelperCardFrame
      label={t(published ? "helper_publish_title_published" : "helper_publish_title_unpublished")}
      icon={<Send className="size-4" />}
    >
      <ChangeRows changes={change.changes} />
      <p className="text-ax-text-secondary m-0 text-[13px]">
        {t("helper_change_cannot_undo")} {t("helper_publish_where", { section: t("publishing") })}
      </p>
    </HelperCardFrame>
  );
}

/**
 * The card the assistant's helper chat draws for one of its tool calls: a
 * proposal, a change or a publish of this assistant; null for any other call.
 */
export function assistantHelperCardFor(call: ToolCallRecord, assistantId: string): ReactNode {
  const proposal = proposalOf(call, assistantId);
  if (proposal) return <AssistantProposalCard proposal={proposal} assistantId={assistantId} />;
  const change = changeOf(call, assistantId);
  if (!change) return null;
  const published = publishedBy(change);
  return published !== null ? (
    <AssistantPublishCard change={change} published={published} />
  ) : (
    <AssistantChangeCard change={change} assistantId={assistantId} />
  );
}
