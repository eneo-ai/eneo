"use client";
import { dependencySources } from "@eneo/skill-instructions";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient
} from "@tanstack/react-query";
import { CircleAlert, RefreshCw } from "lucide-react";
import { useTranslations } from "use-intl";
import { useRef, useState, type RefObject } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { useAppContext } from "@/components/providers/app-context";
import { queuePartnerUpdate } from "@/features/chat/partner-updates";
import { useSpace } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { useFocusRescue } from "@/lib/focus-rescue";
import type { Schema } from "@/lib/api/models";
import {
  activateBinding,
  bindingsFromSummaries,
  removeBinding,
  reviseBinding,
  type Binding
} from "./skill-bindings";
import { skillQueryKey } from "./skill-revisions";

type Configuration = Schema<"AssistantSkillConfigurationPublic">;
type Summary = Schema<"AssistantSkillBindingSummary">;
type Reason = Schema<"PersonalSkillLayerReason">;
type Translate = ReturnType<typeof useTranslations>;

export type PersonalSkillMode = Schema<"SkillActivationMode"> | "off";

/** What the person changed: a Skill's mode, or the version the chat pins. */
export type PersonalSkillChange =
  | {
      kind: "mode";
      skillId: string;
      mode: PersonalSkillMode;
      /** The version a Skill pins when this change adds it: its current one. */
      revisionId: string;
    }
  | { kind: "revision"; skillId: string; revisionId: string };

/** One of the person's own Skills as the personal chat has it. */
export type PersonalSkillRow = {
  skillId: string;
  name: string;
  description: string;
  mode: PersonalSkillMode;
  /** An administrator blocked it: it does not run and cannot be changed. */
  blocked: boolean;
  /** The version a new binding pins (the Skill's current one). */
  revisionId: string;
  /** The version the chat pins, when the Skill is in it. */
  pinnedNumber: number | null;
  /** The newer version the chat could move to, when it pins an older one. */
  latest: { id: string; number: number } | null;
  dependencies?: Summary["dependencies"];
  usedVia?: string[];
};

/** ErrorCodes.PERSONAL_SKILLS_REJECTED: the save would not run as configured. */
const PERSONAL_SKILLS_REJECTED = 9080;
/** Own Skills per library page, as on the Skills page. */
const LIBRARY_PAGE = 25;
/** Beyond this many own Skills the list gets a search field. */
const SEARCH_AFTER = 7;

const REASON_KEYS: Record<Reason, string> = {
  permission_missing: "personal_chat_skills_reason_permission_missing",
  attachment_limit_exceeded: "personal_chat_skills_reason_attachment_limit_exceeded",
  model_context_exceeded: "personal_chat_skills_reason_model_context_exceeded",
  on_demand_unavailable: "personal_chat_skills_reason_on_demand_unavailable",
  personal_skill_does_not_fit: "personal_chat_skills_reason_personal_skill_does_not_fit",
  organisation_skill_crowded_out: "personal_chat_skills_reason_organisation_skill_crowded_out"
};

const MODE_KEYS: Record<PersonalSkillMode, string> = {
  off: "personal_chat_skills_mode_off",
  on_demand: "skills_activation_mode_on_demand",
  always: "skills_activation_mode_always"
};

export function modeLabel(mode: PersonalSkillMode, t: Translate): string {
  return t(MODE_KEYS[mode]);
}

/** Why the person's own Skills do not run, in plain words. */
export function layerReasonText(reason: Reason, detail: unknown, t: Translate): string {
  if (reason === "on_demand_unavailable" && detail === "selective_activation_disabled")
    return t("personal_chat_skills_reason_on_demand_disabled");
  return t(REASON_KEYS[reason]);
}

function isReason(value: unknown): value is Reason {
  return typeof value === "string" && value in REASON_KEYS;
}

/** A refused save in the words of the layer's reasons, or the general failure. */
function saveFailureText(error: unknown, t: Translate): string {
  if (error instanceof EneoApiError) {
    const details = (error.details ?? {}) as { reason?: unknown; detail?: unknown };
    if (error.code === PERSONAL_SKILLS_REJECTED && isReason(details.reason))
      return layerReasonText(details.reason, details.detail, t);
    if (error.status === 403) return layerReasonText("permission_missing", null, t);
  }
  return t("personal_chat_skills_save_failed");
}

function applyChange(bindings: Binding[], change: PersonalSkillChange): Binding[] {
  if (change.kind === "revision") return reviseBinding(bindings, change.skillId, change.revisionId);
  if (change.mode === "off") return removeBinding(bindings, change.skillId);
  if (bindings.some((binding) => binding.skill_id === change.skillId))
    return activateBinding(bindings, change.skillId, change.mode);
  return [
    ...bindings,
    { skill_id: change.skillId, skill_revision_id: change.revisionId, activation_mode: change.mode }
  ];
}

/**
 * The one owner of the personal chat's own Skills, for the composer control
 * and the personal space's Skills pages. The configuration query holds only
 * what is saved; a change shows at once as a pending mutation laid over it,
 * so a refused one rolls back by itself. Each change is saved through the
 * composer's partner update queue (a question sent right after waits for it)
 * and applied to what the server has saved when its turn comes, read then:
 * never to the cache, which can miss an earlier change. The library is read a
 * page at a time and searched on the server; the Skills in the chat are
 * listed whether or not their page has loaded. Every key sits under the
 * space's Skills key: an edit, a new version or a deletion there refreshes
 * the chat's view too.
 */
export function usePersonalChatSkills({
  withLibrary = false,
  search = ""
}: {
  withLibrary?: boolean;
  /** The library search (debounced by the caller). */
  search?: string;
} = {}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const { space } = useSpace();
  const { can } = useAppContext();
  const assistant = space.personal ? space.default_assistant : null;
  const assistantId = assistant?.id ?? null;
  const canEdit = can({ allOf: ["personal_chat", "personal_skills"] });
  const spaceSkillsKey = skillQueryKey({ type: "space", spaceId: space.id });
  // A model switch can pause or resume the layer, so the model is part of the
  // key; the scope (without it) covers the configuration under every model.
  const configurationScope = [...spaceSkillsKey, { personalChat: assistantId }];
  const configurationKey = [
    ...spaceSkillsKey,
    { personalChat: assistantId, model: assistant?.completion_model?.id ?? null }
  ];
  const mutationKey = ["personal-chat-skills", assistantId];
  const readSaved = (): Promise<Configuration> =>
    unwrap(
      browserApi.GET("/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/configuration/", {
        params: { path: { space_id: space.id, assistant_id: assistantId! } }
      })
    );

  const configuration = useQuery({
    queryKey: configurationKey,
    enabled: assistantId !== null,
    placeholderData: keepPreviousData,
    queryFn: readSaved
  });

  const library = useInfiniteQuery({
    queryKey: [...spaceSkillsKey, { personalChatLibrary: search }],
    enabled: withLibrary && canEdit && assistantId !== null,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        browserApi.GET("/api/v1/spaces/{space_id}/skills/", {
          params: {
            path: { space_id: space.id },
            query: { limit: LIBRARY_PAGE, cursor: pageParam, q: search || undefined }
          },
          signal
        })
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    // While a search runs, the earlier results stay instead of a skeleton.
    placeholderData: keepPreviousData
  });

  // A refusal belongs to one attempt: a later choice for the same Skill
  // (pending or saved) retires it, and other rows keep theirs.
  const attempts = useRef(0);
  const newestAttempt = useRef(new Map<string, number>());
  const [failures, setFailures] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationKey,
    mutationFn: (change: PersonalSkillChange) =>
      queuePartnerUpdate(async () => {
        // Read when this change's turn comes. The cache may miss an earlier
        // change (its refresh failed, or nothing on screen reads it any more),
        // and a list built from it would undo that change. Unread, nothing is sent.
        const saved = await readSaved().catch(() => {
          throw new Error("The personal chat's saved Skills could not be read");
        });
        await unwrap(
          browserApi.POST("/api/v1/assistants/{id}/", {
            params: { path: { id: assistantId! } },
            body: { skill_bindings: applyChange(bindingsFromSummaries(saved.bindings), change) }
          })
        );
      }),
    onMutate: (change) => {
      attempts.current += 1;
      newestAttempt.current.set(change.skillId, attempts.current);
      setFailures((current) => {
        const next = { ...current };
        delete next[change.skillId];
        return next;
      });
      return attempts.current;
    },
    // Still pending until the view shows the saved result, so no choice flickers back.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: configurationScope }),
    onError: (error, change, attempt) => {
      if (newestAttempt.current.get(change.skillId) !== attempt) return;
      const message = saveFailureText(error, t);
      setFailures((current) => ({ ...current, [change.skillId]: message }));
      announce(message);
    }
  });
  const pending = useMutationState({
    filters: { mutationKey, status: "pending" },
    select: (mutation) => mutation.state.variables as PersonalSkillChange
  });

  const data = configuration.data;
  const summaries = new Map((data?.bindings ?? []).map((summary) => [summary.skill_id, summary]));
  const own = pending.reduce(
    (bindings, change) => applyChange(bindings, change),
    bindingsFromSummaries(data?.bindings ?? [])
  );
  const chosen = new Map(own.map((binding) => [binding.skill_id, binding]));
  const organisation = [...(data?.organisation_bindings ?? [])].sort(
    (left, right) => left.position - right.position
  );
  const layer = data?.personal_layer ?? null;
  const helperSources = dependencySources(
    (data?.bindings ?? []).filter(
      (binding) => chosen.get(binding.skill_id)?.skill_revision_id === binding.skill_revision_id
    )
  );

  function row(skillId: string, name: string, description: string, revisionId: string) {
    const summary: Summary | undefined = summaries.get(skillId);
    const binding = chosen.get(skillId);
    const latestId = summary?.attachable_revision_id ?? null;
    const latestNumber = summary?.attachable_revision_number ?? null;
    return {
      skillId,
      name: summary?.display_name ?? name,
      description: summary?.description ?? description,
      mode: binding ? (binding.activation_mode ?? "always") : "off",
      blocked: summary?.execution_blocked ?? false,
      revisionId,
      pinnedNumber: summary?.revision_number ?? null,
      dependencies:
        binding?.skill_revision_id === summary?.skill_revision_id ? summary?.dependencies : [],
      usedVia: helperSources.get(skillId) ?? [],
      latest:
        binding &&
        latestId !== null &&
        latestNumber !== null &&
        latestId !== binding.skill_revision_id &&
        !summary?.execution_blocked &&
        // A deactivated Skill keeps running at its pin but cannot move.
        summary?.is_active !== false
          ? { id: latestId, number: latestNumber }
          : null
    } satisfies PersonalSkillRow;
  }

  // The library's order, so a row never moves when its mode changes. An
  // inactive Skill can't be added, so only a bound one stays listed. The
  // Skills in the chat follow, wherever their library page is (not loaded,
  // failed, or not yet reached), as far as they match the search.
  const pages = library.data?.pages ?? [];
  const listed = canEdit
    ? pages
        .flatMap((page) => page.items)
        .filter((skill) => skill.is_active || summaries.has(skill.id))
    : [];
  const listedIds = new Set(listed.map((skill) => skill.id));
  const term = search.toLocaleLowerCase();
  const rows: PersonalSkillRow[] = [
    ...listed.map((skill) =>
      row(skill.id, skill.display_name, skill.description, skill.current_revision_id)
    ),
    ...(data?.bindings ?? [])
      .filter((summary) => !listedIds.has(summary.skill_id))
      .filter((summary) =>
        `${summary.display_name} ${summary.description}`.toLocaleLowerCase().includes(term)
      )
      .map((summary) =>
        // Re-added after Av, it joins at the newest version, not the old pin.
        row(
          summary.skill_id,
          summary.display_name,
          summary.description,
          summary.attachable_revision_id ?? summary.skill_revision_id
        )
      )
  ];

  // What runs: the organisation's unblocked Skills, and the person's own
  // unless their layer is paused.
  const runningModes = [
    ...organisation.filter((summary) => !summary.execution_blocked).map((s) => s.activation_mode),
    ...(layer?.status === "suspended"
      ? []
      : own
          .filter((binding) => !summaries.get(binding.skill_id)?.execution_blocked)
          .map((binding) => binding.activation_mode ?? "always"))
  ];
  const running = data
    ? {
        total: runningModes.length,
        always: runningModes.filter((mode) => mode === "always").length,
        onDemand: runningModes.filter((mode) => mode === "on_demand").length
      }
    : null;

  return {
    canEdit,
    configuration,
    library,
    layer,
    organisation,
    rows,
    running,
    /** The composer shows the control to people who can choose, or when anything is in the chat. */
    visible:
      assistantId !== null &&
      (canEdit || organisation.length > 0 || (data?.bindings.length ?? 0) > 0),
    /** The search field is offered beyond seven own Skills, or when there are more pages. */
    searchable:
      search !== "" ||
      library.hasNextPage ||
      (library.data?.pages[0]?.items.length ?? 0) > SEARCH_AFTER,
    /** The refusal shown at each Skill, by Skill id. */
    failures,
    /** Forgets every refusal (the control closed: they belong to that visit). */
    dismissFailures: () => setFailures({}),
    change: (change: PersonalSkillChange) => save.mutate(change)
  };
}

/** A Skill's place in the personal chat, for the personal space's Skills list. */
export function PersonalChatSkillStatus({ skillId }: { skillId: string }) {
  const t = useTranslations();
  const { rows } = usePersonalChatSkills();
  const row = rows.find((candidate) => candidate.skillId === skillId);
  if (!row || row.mode === "off") return null;
  return (
    <Badge
      variant="blue"
      label={t("personal_chat_skills_status_badge", { mode: modeLabel(row.mode, t) })}
    />
  );
}

/**
 * On a Skill's page: the personal chat runs an older version of it, with the
 * move to the latest one. Focus goes to `rescueTarget` (the page heading)
 * once the notice has gone.
 */
export function PersonalChatVersionNotice({
  skillId,
  rescueTarget
}: {
  skillId: string;
  rescueTarget: RefObject<HTMLElement | null>;
}) {
  const t = useTranslations();
  const { rows, canEdit, change, failures } = usePersonalChatSkills();
  const rescue = useFocusRescue();
  const row = rows.find((candidate) => candidate.skillId === skillId);
  const error = failures[skillId] ?? null;
  if (!row?.latest || row.pinnedNumber === null) {
    return error ? <FailureText message={error} /> : null;
  }
  const latest = row.latest;
  return (
    <div className="flex flex-col gap-2">
      <Banner
        status="info"
        title={t("personal_chat_skills_version_notice", { version: row.pinnedNumber })}
        endContent={
          canEdit ? (
            <Button
              size="sm"
              label={t("personal_chat_skills_use_latest")}
              icon={<RefreshCw aria-hidden="true" />}
              onClick={() => {
                change({ kind: "revision", skillId, revisionId: latest.id });
                rescue(() => rescueTarget.current);
              }}
            />
          ) : undefined
        }
      />
      {error && <FailureText message={error} />}
    </div>
  );
}

/** A refused change, said next to the control that made it (text and an icon). */
export function FailureText({ message }: { message: string }) {
  return (
    <p className="text-ax-error flex items-start gap-1.5 text-xs">
      <CircleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0" />
      {message}
    </p>
  );
}
