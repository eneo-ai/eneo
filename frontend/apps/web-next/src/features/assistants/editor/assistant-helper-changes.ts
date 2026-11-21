import type { useTranslations } from "use-intl";
import {
  capabilityBlockReason,
  getCapability,
  readinessKey
} from "@/features/capabilities/capabilities";
import type { ToolCallRecord } from "@/features/chat/side-panel/message-tool-calls";
import type { Space } from "@/features/spaces/space";
import {
  canEditAssistantRetention,
  canToggleAssistantInsights,
  capabilityAvailability,
  capabilityBlockMessageKey,
  knowledgeBlockedByMcp,
  mcpBlockedByKnowledge,
  mcpServerUnavailableReason,
  modelBlocksTools
} from "./assistant-editor-rules";
import {
  assistantToolModel,
  effectiveAssistantModels,
  isMcpEnforced,
  isPromptLocked,
  lockedAssistantModel
} from "./effective-config";
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
 * `knowledge_mode`, `inline_file_text`, a list in `LIST_FIELDS`,
 * `mcp_tools`, `rerank_model_id`, `document_template`,
 * `data_retention_days`, `insight_enabled`, and `published` for a publish).
 * A list is `{id, name}` by name (a function's `id` is its purpose), the
 * tool settings `{id, name, is_enabled}`, the ranking model `{id, name}` or
 * null, the template `{mode, template_id, name}`. A text too long for the
 * call's data comes without its before and after (`tooLong`); the request
 * bodies hold it whole.
 */
export type SettingChange = { field: string; before: unknown; after: unknown; tooLong: boolean };

/** A `propose_changes` call's proposal: the settings it would change and the request that changes them. */
export type AssistantProposal = { changes: SettingChange[]; update: AssistantUpdate };

/**
 * An `update_assistant` or `publish_assistant` call's change: the settings
 * it changed and the request that undoes it (none for a publish).
 */
export type AssistantChange = { changes: SettingChange[]; undo: AssistantUpdate | null };

/** The list settings, compared as sets of ids. */
export const LIST_FIELDS: ReadonlySet<string> = new Set([
  "groups",
  "websites",
  "integration_knowledge_list",
  "mcp_servers",
  "enabled_capabilities"
]);

/**
 * One function a change switched, as the form names it to mark its row:
 * `enabled_capabilities.<purpose>`.
 */
export const FUNCTION_FIELD_PREFIX = "enabled_capabilities.";

/** The knowledge lists. */
const KNOWLEDGE_LISTS = ["groups", "websites", "integration_knowledge_list"] as const;

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

/** An entry of a list setting, as the calls and the cards read it. */
export type ListEntry = { id: string; name: string | null };

/** An assistant's own setting of one MCP tool. */
export type ToolEntry = ListEntry & { isEnabled: boolean };

/**
 * The entries of a list value: items as a call gives them (`{id, name}`),
 * as a request sends them (`{id}`, a tool's `{tool_id}`) or a function's
 * purpose alone. Anything else is no entry.
 */
export function listEntries(value: unknown): ListEntry[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): ListEntry[] => {
    if (typeof item === "string") return [{ id: item, name: null }];
    if (!isRecord(item)) return [];
    const id = item.id ?? item.tool_id;
    if (typeof id !== "string") return [];
    return [{ id, name: typeof item.name === "string" && item.name ? item.name : null }];
  });
}

/** The tool settings of a value: by id, each on or off. */
export function toolEntries(value: unknown): ToolEntry[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): ToolEntry[] => {
    const [entry] = listEntries([item]);
    return entry && isRecord(item) && typeof item.is_enabled === "boolean"
      ? [{ ...entry, isEnabled: item.is_enabled }]
      : [];
  });
}

const sameIds = (a: unknown, b: unknown) => {
  const first = new Set(listEntries(a).map((entry) => entry.id));
  const second = new Set(listEntries(b).map((entry) => entry.id));
  return first.size === second.size && [...first].every((id) => second.has(id));
};

const sameTools = (a: unknown, b: unknown) => {
  const first = new Map(toolEntries(a).map((entry) => [entry.id, entry.isEnabled]));
  const second = new Map(toolEntries(b).map((entry) => [entry.id, entry.isEnabled]));
  return first.size === second.size && [...first].every(([id, on]) => second.get(id) === on);
};

/** A template choice as one value: its mode and its template. */
const templateKey = (value: unknown) =>
  isRecord(value)
    ? `${typeof value.mode === "string" ? value.mode : "default"}:${typeof value.template_id === "string" ? value.template_id : ""}`
    : "default:";

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
 * The change an `update_assistant` or `publish_assistant` call made to this
 * assistant; null for any other call, and for one that changed nothing.
 */
export function changeOf(
  call: Pick<ToolCallRecord, "toolName" | "structuredContent" | "serverName" | "isInternal">,
  assistantId: string
): AssistantChange | null {
  const content =
    contentOf(call, "update_assistant", assistantId) ??
    contentOf(call, "publish_assistant", assistantId);
  if (!content) return null;
  const changes = settingChanges(content.changes);
  if (changes.length === 0) return null;
  return { changes, undo: isRecord(content.undo) ? (content.undo as AssistantUpdate) : null };
}

/**
 * Whether a change is a publish: the assistant published (true) or
 * unpublished (false); null for any other change.
 */
export function publishedBy(change: AssistantChange): boolean | null {
  const [only] = change.changes;
  return change.changes.length === 1 &&
    only?.field === "published" &&
    typeof only.after === "boolean"
    ? only.after
    : null;
}

/**
 * A setting's value on the assistant now, as the helper chat's calls give
 * it. A list is its ids (`[{id}]`, a function's purpose as its id), the
 * tool settings `[{id, is_enabled}]`, the ranking model `{id}`: what they
 * are compared by.
 */
export function currentSetting(assistant: Assistant, field: string): unknown {
  const ids = (items: readonly { id: string }[] | undefined) =>
    (items ?? []).map((item) => ({ id: item.id }));
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
    case "groups":
    case "websites":
    case "integration_knowledge_list":
    case "mcp_servers":
      return ids(assistant[field]);
    case "enabled_capabilities":
      return (assistant.enabled_capabilities ?? []).map((purpose) => ({ id: purpose }));
    case "mcp_tools":
      return (assistant.mcp_tools ?? []).map((tool) => ({
        id: tool.tool_id,
        is_enabled: tool.is_enabled
      }));
    case "rerank_model_id":
      return assistant.rerank_model_id ? { id: assistant.rerank_model_id } : null;
    case "document_template":
      return assistant.document_template ?? { mode: "default", template_id: null };
    case "published":
      return assistant.published ?? false;
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
 * goes back to the model's default (null). The tool settings and the
 * ranking model are read as `currentSetting` gives them.
 */
export function settingInRequest(body: AssistantUpdate, field: string): unknown {
  if (field === "prompt")
    return body.prompt === undefined ? undefined : (body.prompt?.text ?? null);
  if (field.startsWith(KWARGS)) {
    if (body.completion_model_kwargs === undefined) return undefined;
    const kwargs = (body.completion_model_kwargs ?? {}) as Record<string, unknown>;
    return kwargs[field.slice(KWARGS.length)] ?? null;
  }
  if (field === "mcp_tools" && body.mcp_tools) {
    return body.mcp_tools.map((tool) => ({ id: tool.tool_id, is_enabled: tool.is_enabled }));
  }
  if (field === "rerank_model_id" && typeof body.rerank_model_id === "string") {
    return { id: body.rerank_model_id };
  }
  return (body as Record<string, unknown>)[field];
}

const modelId = (value: unknown) =>
  isRecord(value) && typeof value.id === "string" ? value.id : null;

/**
 * Whether two values of a setting are the same: a model by its id, an
 * empty text as no text, a list as a set of ids, the tool settings by id
 * and state, a template by its mode and template.
 */
export function sameSetting(field: string, a: unknown, b: unknown): boolean {
  if (field === "completion_model" || field === "rerank_model_id") return modelId(a) === modelId(b);
  if (TEXT_FIELDS.has(field)) return (a ?? "") === (b ?? "");
  if (LIST_FIELDS.has(field)) return sameIds(a, b);
  if (field === "mcp_tools") return sameTools(a, b);
  if (field === "document_template") return templateKey(a) === templateKey(b);
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

/** What a request would do the person may not, or may: hidden, or offered with the reason it is disabled. */
export type RequestGate = { offered: false } | { offered: true; disabledReason: string | null };

type Translate = ReturnType<typeof useTranslations>;

/**
 * What the gate reads beyond the assistant: the space as the editor has it,
 * whether the person may edit the space, and the choices the editor offers
 * for the ranking model and the template (undefined while not known; the
 * server then has the last word).
 */
export type GateContext = {
  space: Pick<
    Space,
    | "personal"
    | "completion_models"
    | "mcp_servers"
    | "enabled_capabilities"
    | "available_capabilities"
  >;
  canEditSpace: boolean;
  rerankModels?: readonly { id: string }[];
  templates?: readonly { id: string }[];
};

/** The name a call gives the item `id` of `field`, before or after. */
function nameIn(changes: readonly SettingChange[], field: string, id: string): string | null {
  for (const change of changes) {
    if (change.field !== field) continue;
    for (const value of [change.after, change.before]) {
      for (const item of Array.isArray(value) ? value : [value]) {
        if (!isRecord(item) || (item.id !== id && item.template_id !== id)) continue;
        if (typeof item.name === "string" && item.name) return item.name;
      }
    }
  }
  return null;
}

/** A function as the editor names it; one it does not know by its purpose. */
export function functionName(purpose: string, t: Translate): string {
  return getCapability(purpose) ? t(purpose) : purpose;
}

/**
 * Knowledge and MCP servers exclude each other in the editor, one picker at
 * a time: a request that changes both is offered where the editor would let
 * the person make it in one order or the other.
 */
function exclusionReason(body: AssistantUpdate, assistant: Assistant, t: Translate) {
  const editsKnowledge = KNOWLEDGE_LISTS.some((key) => body[key] != null);
  const editsServers = body.mcp_servers != null || body.mcp_tools != null;
  if (!editsKnowledge && !editsServers) return null;
  const knowledgeNow = KNOWLEDGE_LISTS.reduce((sum, key) => sum + assistant[key].length, 0);
  const knowledgeAfter = KNOWLEDGE_LISTS.reduce(
    (sum, key) => sum + (body[key] ?? assistant[key]).length,
    0
  );
  const serversNow = assistant.mcp_servers?.length ?? 0;
  const serversAfter = body.mcp_servers?.length ?? serversNow;
  const knowledgeOpen = !knowledgeBlockedByMcp(knowledgeNow, serversNow);
  const serversOpen = !mcpBlockedByKnowledge(knowledgeNow, serversNow);
  const reachable =
    editsKnowledge && editsServers
      ? (knowledgeOpen && !mcpBlockedByKnowledge(knowledgeAfter, serversNow)) ||
        (serversOpen && !knowledgeBlockedByMcp(knowledgeNow, serversAfter))
      : editsKnowledge
        ? knowledgeOpen
        : serversOpen;
  if (reachable) return null;
  return t(
    knowledgeOpen ? "mcp_disabled_when_knowledge_active" : "knowledge_disabled_when_mcp_active"
  );
}

/**
 * What switching on an MCP server, one of its tools or a function would
 * meet in the editor: a server the space no longer offers or an
 * administrator turned off, and any of them while the model cannot call
 * tools; a function the space does not offer or no provider is ready for.
 */
function turnOnReason(
  body: AssistantUpdate,
  changes: readonly SettingChange[],
  assistant: Assistant,
  context: GateContext,
  t: Translate
): string | null {
  const models = context.space.completion_models;
  const chosen = body.completion_model?.id;
  const blocks = modelBlocksTools(
    assistantToolModel(
      models,
      chosen
        ? {
            completion_model: models.find((model) => model.id === chosen) ?? null,
            effective_config: assistant.effective_config
          }
        : assistant
    )
  );
  const cannot = (name: string, reason: string) =>
    t("helper_card_cannot_turn_on", { name, reason });

  const attached = new Set((assistant.mcp_servers ?? []).map((server) => server.id));
  for (const { id } of body.mcp_servers ?? []) {
    if (attached.has(id)) continue;
    const offered = (context.space.mcp_servers ?? []).find((server) => server.id === id);
    const name = offered?.name ?? nameIn(changes, "mcp_servers", id) ?? "";
    if (!offered) return t("helper_card_server_not_offered", { name });
    const unavailable = mcpServerUnavailableReason(offered, blocks);
    if (unavailable) return cannot(name, t(readinessKey(unavailable)));
  }

  const toolsOn = new Set(
    (assistant.mcp_tools ?? []).filter((tool) => tool.is_enabled).map((tool) => tool.tool_id)
  );
  const switchedOn = (body.mcp_tools ?? []).find(
    (tool) => tool.is_enabled && !toolsOn.has(tool.tool_id)
  );
  if (switchedOn && blocks) {
    return cannot(
      nameIn(changes, "mcp_tools", switchedOn.tool_id) ?? t("helper_card_unnamed_tool"),
      t(readinessKey("model_no_tool_calling"))
    );
  }

  const enabled = new Set(assistant.enabled_capabilities ?? []);
  for (const purpose of body.enabled_capabilities ?? []) {
    if (enabled.has(purpose)) continue;
    const availability = capabilityAvailability(assistant, context.space, purpose);
    const blocked = capabilityBlockReason({
      enabled: false,
      spaceEnabled: (context.space.enabled_capabilities ?? []).includes(purpose),
      available: availability?.available === true,
      modelSupportsTools: !blocks
    });
    if (blocked) {
      return cannot(functionName(purpose, t), t(capabilityBlockMessageKey(blocked, availability)));
    }
  }
  return null;
}

/**
 * Why the editor's own control would not let the person send `body`; null
 * where it would: what a policy decides (the instructions, a locked model,
 * a governed list of MCP servers and functions), a model the editor would
 * not offer, retention and insights without the right, knowledge and MCP
 * servers excluding each other, what cannot be switched on, and a ranking
 * model or template no longer offered. The first that applies is said.
 */
function blockedReason(
  body: AssistantUpdate,
  changes: readonly SettingChange[],
  assistant: Assistant,
  context: GateContext,
  t: Translate
): string | null {
  const config = assistant.effective_config;
  const models = [...context.space.completion_models];
  if (body.prompt !== undefined && body.prompt !== null && isPromptLocked(config)) {
    return t("helper_card_locked", { setting: t("prompt") });
  }
  const id = body.completion_model?.id;
  if (id) {
    const locked = lockedAssistantModel(models, config);
    if (locked && locked.id !== id) {
      return t("helper_card_locked", { setting: t("completion_model") });
    }
    if (!locked && !effectiveAssistantModels(models, config).some((m) => m.id === id)) {
      return t("helper_card_model_not_offered", {
        model: nameIn(changes, "completion_model", id) ?? ""
      });
    }
  }
  if (isMcpEnforced(config)) {
    if (body.mcp_servers != null || body.mcp_tools != null) {
      return t("helper_card_locked", { setting: t("mcp_servers") });
    }
    if (body.enabled_capabilities != null) {
      return t("helper_card_locked", { setting: t("capabilities") });
    }
  }
  if (
    body.data_retention_days !== undefined &&
    !canEditAssistantRetention(context.space, context.canEditSpace)
  ) {
    return t("conversation_retention_space_admin_only");
  }
  if (body.insight_enabled != null && !canToggleAssistantInsights(assistant)) {
    return t("only_space_admins_toggle");
  }
  const excluded = exclusionReason(body, assistant, t);
  if (excluded) return excluded;
  const turnOn = turnOnReason(body, changes, assistant, context, t);
  if (turnOn) return turnOn;
  const rerank = body.rerank_model_id;
  if (
    typeof rerank === "string" &&
    context.rerankModels &&
    !context.rerankModels.some((model) => model.id === rerank)
  ) {
    return t("helper_card_model_not_offered", {
      model: nameIn(changes, "rerank_model_id", rerank) ?? t("material_reranker_missing")
    });
  }
  const template = body.document_template;
  if (
    template?.mode === "selected" &&
    context.templates &&
    !context.templates.some((item) => item.id === template.template_id)
  ) {
    return t("helper_card_template_not_offered", {
      name:
        (template.template_id && nameIn(changes, "document_template", template.template_id)) ??
        t("document_template_choice_selected")
    });
  }
  return null;
}

/**
 * Whether the person may send `body` as their own save, with the same
 * conditions the editor's own controls apply (`assistant-editor-rules.ts`):
 * nothing without edit rights; with them, a reason in words where the
 * editor's control for a setting in it is disabled or absent for this
 * person. `changes` name what the reason is about.
 */
export function requestGate(
  body: AssistantUpdate,
  changes: readonly SettingChange[],
  assistant: Assistant,
  context: GateContext,
  t: Translate
): RequestGate {
  if (!(assistant.permissions ?? []).includes("edit")) return { offered: false };
  return { offered: true, disabledReason: blockedReason(body, changes, assistant, context, t) };
}
