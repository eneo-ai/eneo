import type { useTranslations } from "use-intl";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import type { Schema } from "@/lib/api/models";
import { effectiveAssistantModels, isPromptLocked, lockedAssistantModel } from "./effective-config";
import type { ModelKwargName } from "./model-kwargs";
import type { Assistant, AssistantUpdate } from "./use-assistant";

/** The loopback server the assistant's helper chat runs its tools on (the backend's `ASSISTANT_SERVER_NAME`). */
export const ASSISTANT_SERVER_NAME = "assistant";

/** A call on Eneo's own assistant server; an external server an admin named "assistant" does not count. */
export function isAssistantToolCall(
  call: Pick<ToolCallRecord, "serverName" | "isInternal">
): boolean {
  return call.serverName === ASSISTANT_SERVER_NAME && call.isInternal !== false;
}

/**
 * One setting a call of the helper chat changed or would change, as the
 * call gives it: `field` names the setting (`name`, `description`,
 * `prompt`, `completion_model`, `completion_model_kwargs.<setting>`,
 * `knowledge_mode`, `inline_file_text`). A text too long for the call's data
 * comes without its before and after (`tooLong`); the request bodies hold
 * it whole.
 */
export type SettingChange = { field: string; before: unknown; after: unknown; tooLong: boolean };

/** A `propose_changes` call's proposal: the settings it would change and the request that changes them. */
export type AssistantProposal = { changes: SettingChange[]; update: AssistantUpdate };

/** An `update_assistant` call's change: the settings it changed and the request that undoes it. */
export type AssistantChange = { changes: SettingChange[]; undo: AssistantUpdate | null };

const KWARGS = "completion_model_kwargs.";
const TEXT_FIELDS = new Set(["name", "description", "prompt"]);
const KWARG_NAMES = new Set<string>([
  "temperature",
  "top_p",
  "reasoning_effort",
  "verbosity",
  "presence_penalty",
  "frequency_penalty",
  "top_k"
]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** The model setting a `completion_model_kwargs.<setting>` field names, when it is one the editor shows. */
export function kwargOf(field: string): ModelKwargName | null {
  if (!field.startsWith(KWARGS)) return null;
  const name = field.slice(KWARGS.length);
  return KWARG_NAMES.has(name) ? (name as ModelKwargName) : null;
}

function settingChanges(value: unknown): SettingChange[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): SettingChange[] =>
    isRecord(item) && typeof item.field === "string" && item.field
      ? [
          {
            field: item.field,
            before: item.before ?? null,
            after: item.after ?? null,
            tooLong: item.too_long === true
          }
        ]
      : []
  );
}

/** The call's data when it is one of the helper chat's about this assistant. */
function contentOf(
  call: Pick<ToolCallRecord, "toolName" | "structuredContent" | "serverName" | "isInternal">,
  toolName: string,
  assistantId: string
): Record<string, unknown> | null {
  if (!isAssistantToolCall(call) || call.toolName !== toolName) return null;
  const content = call.structuredContent;
  return content && content.target_id === assistantId ? content : null;
}

/**
 * The proposal a `propose_changes` call about this assistant returned; null
 * for any other call, and for one that found nothing to change.
 */
export function proposalOf(
  call: Pick<ToolCallRecord, "toolName" | "structuredContent" | "serverName" | "isInternal">,
  assistantId: string
): AssistantProposal | null {
  const proposal = contentOf(call, "propose_changes", assistantId)?.proposal;
  if (!isRecord(proposal) || !isRecord(proposal.update)) return null;
  const changes = settingChanges(proposal.changes);
  return changes.length > 0 ? { changes, update: proposal.update as AssistantUpdate } : null;
}

/**
 * The change an `update_assistant` call made to this assistant; null for
 * any other call, and for one that changed nothing.
 */
export function changeOf(
  call: Pick<ToolCallRecord, "toolName" | "structuredContent" | "serverName" | "isInternal">,
  assistantId: string
): AssistantChange | null {
  const content = contentOf(call, "update_assistant", assistantId);
  if (!content) return null;
  const changes = settingChanges(content.changes);
  if (changes.length === 0) return null;
  return { changes, undo: isRecord(content.undo) ? (content.undo as AssistantUpdate) : null };
}

/** A setting's value on the assistant now, as the helper chat's calls give it. */
export function currentSetting(assistant: Assistant, field: string): unknown {
  switch (field) {
    case "name":
      return assistant.name;
    case "description":
      return assistant.description ?? null;
    case "prompt":
      return assistant.prompt?.text ?? null;
    case "completion_model":
      return assistant.completion_model
        ? { id: assistant.completion_model.id, name: assistant.completion_model.name }
        : null;
    case "knowledge_mode":
      return assistant.knowledge_mode;
    case "inline_file_text":
      return assistant.inline_file_text;
  }
  if (field.startsWith(KWARGS)) {
    const kwargs = (assistant.completion_model_kwargs ?? {}) as Record<string, unknown>;
    return kwargs[field.slice(KWARGS.length)] ?? null;
  }
  return (assistant as Record<string, unknown>)[field] ?? null;
}

/**
 * The value an update request gives a setting; undefined where the request
 * leaves it alone. Model settings are sent whole, so one left out of them
 * goes back to the model's default (null).
 */
export function settingInRequest(body: AssistantUpdate, field: string): unknown {
  if (field === "prompt")
    return body.prompt === undefined ? undefined : (body.prompt?.text ?? null);
  if (field.startsWith(KWARGS)) {
    if (body.completion_model_kwargs === undefined) return undefined;
    const kwargs = (body.completion_model_kwargs ?? {}) as Record<string, unknown>;
    return kwargs[field.slice(KWARGS.length)] ?? null;
  }
  return (body as Record<string, unknown>)[field];
}

const modelId = (value: unknown) =>
  isRecord(value) && typeof value.id === "string" ? value.id : null;

/** Whether two values of a setting are the same: a model by its id, an empty text as no text. */
export function sameSetting(field: string, a: unknown, b: unknown): boolean {
  if (field === "completion_model") return modelId(a) === modelId(b);
  if (TEXT_FIELDS.has(field)) return (a ?? "") === (b ?? "");
  if (a === b) return true;
  if (a === null || b === null || a === undefined || b === undefined) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Whether a proposal is in use: every setting it changes has its value now.
 * A text too long for the call's data is compared with the request's.
 */
export function proposalUsed(proposal: AssistantProposal, assistant: Assistant): boolean {
  return proposal.changes.every((change) => {
    const target = change.tooLong ? settingInRequest(proposal.update, change.field) : change.after;
    return sameSetting(change.field, currentSetting(assistant, change.field), target);
  });
}

/**
 * Where a change the helper made stands now:
 * - `current`: every setting still has the value the change gave it, so it
 *   can be undone (a text too long to compare counts while it is not back
 *   to its value from before);
 * - `undone`: every setting the undo request covers is back to its value
 *   from before;
 * - `changed`: a setting has been changed since, so undoing would overwrite that;
 * - `permanent`: the change has no undo request.
 */
export type ChangeState = "current" | "undone" | "changed" | "permanent";

export function changeState(change: AssistantChange, assistant: Assistant): ChangeState {
  const undo = change.undo;
  const undone = (field: string) => {
    const value = undo ? settingInRequest(undo, field) : undefined;
    return value !== undefined && sameSetting(field, currentSetting(assistant, field), value);
  };
  const undoFields = undo
    ? change.changes.filter((item) => settingInRequest(undo, item.field) !== undefined)
    : [];
  if (undoFields.length === 0) return "permanent";
  const stillMade = change.changes.every((item) =>
    item.tooLong
      ? !undone(item.field)
      : sameSetting(item.field, currentSetting(assistant, item.field), item.after)
  );
  if (stillMade) return "current";
  return undoFields.every((item) => undone(item.field)) ? "undone" : "changed";
}

type SpaceModel = Schema<"CompletionModelPublic">;

/** What a request would do the person may not, or may: hidden, or offered with the reason it is disabled. */
export type RequestGate = { offered: false } | { offered: true; disabledReason: string | null };

type Translate = ReturnType<typeof useTranslations>;

/**
 * Whether the person may send `body` as their own save, as the editor
 * decides it: nothing without edit rights; with them, a reason in words for
 * what an organisation policy decides (the instructions, a locked model) and
 * for a model the editor would not offer (outside the policy's list, or no
 * longer in the space). `changes` name the model.
 */
export function requestGate(
  body: AssistantUpdate,
  changes: SettingChange[],
  assistant: Assistant,
  models: readonly SpaceModel[],
  t: Translate
): RequestGate {
  if (!(assistant.permissions ?? []).includes("edit")) return { offered: false };
  const config = assistant.effective_config;
  if (body.prompt !== undefined && body.prompt !== null && isPromptLocked(config)) {
    return { offered: true, disabledReason: t("helper_card_locked", { setting: t("prompt") }) };
  }
  const id = body.completion_model?.id;
  if (id) {
    const locked = lockedAssistantModel([...models], config);
    if (locked && locked.id !== id) {
      return {
        offered: true,
        disabledReason: t("helper_card_locked", { setting: t("completion_model") })
      };
    }
    if (!locked && !effectiveAssistantModels([...models], config).some((m) => m.id === id)) {
      const named = changes
        .flatMap((change) => [change.before, change.after])
        .find((value) => modelId(value) === id);
      const name = isRecord(named) && typeof named.name === "string" ? named.name : "";
      return { offered: true, disabledReason: t("helper_card_model_not_offered", { model: name }) };
    }
  }
  return { offered: true, disabledReason: null };
}
