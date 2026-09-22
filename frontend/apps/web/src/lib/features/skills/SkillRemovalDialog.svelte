<script lang="ts">
  import {
    EneoError,
    type OrganizationSkillSummaryPublic,
    type SkillRemovalRequest,
    type SkillRemovalResult
  } from "@eneo/eneo-js";
  import { resolve } from "$app/paths";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { getErrorMessage, SKILL_STILL_ATTACHED } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { formatSkillUsage } from "./skillUsage";
  import { TriangleAlert } from "lucide-svelte";
  import { onDestroy, tick } from "svelte";

  type Target = Pick<OrganizationSkillSummaryPublic, "id" | "display_name" | "usage">;
  let {
    skills,
    onRemove,
    onRemoved,
    onClose,
    onExclude
  }: {
    skills: Target[];
    onRemove: (request: SkillRemovalRequest) => Promise<SkillRemovalResult>;
    onRemoved: (result: SkillRemovalResult) => Promise<void>;
    onClose: () => void;
    onExclude: (ids: string[]) => void;
  } = $props();

  let saving = $state(false);
  let error = $state<string | null>(null);
  let serverBlockers = $state<string[]>([]);
  // On by default: an admin removing a Skill nearly always wants it gone
  // everywhere, and cannot edit other users' personal spaces by hand.
  let detachBindings = $state(true);
  const detachCheckboxId = "skill-removal-detach";
  let restoreFocus = true;
  const previousFocus = typeof document === "undefined" ? null : document.activeElement;
  const focusFallback =
    typeof document === "undefined"
      ? null
      : document.querySelector<HTMLElement>("[data-skill-removal-focus]");
  onDestroy(() => {
    void tick().then(() => {
      if (!restoreFocus || typeof HTMLElement === "undefined") return;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
      else if (focusFallback?.isConnected) focusFallback.focus();
    });
  });
  const blockers = $derived(
    skills.filter(
      (skill) =>
        skill.usage.assistant_count > 0 ||
        skill.usage.app_count > 0 ||
        skill.usage.personal_chat_pinned ||
        serverBlockers.includes(skill.id)
    )
  );
  const isBlocked = $derived((skill: Target) => blockers.some((item) => item.id === skill.id));
  const personalChatAffected = $derived(blockers.some((skill) => skill.usage.personal_chat_pinned));
  const canRemove = $derived(skills.length > 0 && (blockers.length === 0 || detachBindings));

  async function remove(event: MouseEvent) {
    event.preventDefault();
    if (saving || !canRemove) return;
    saving = true;
    error = null;
    let result: SkillRemovalResult;
    try {
      // Only authorise detaching bindings the admin has seen listed; a
      // binding the server discovers later surfaces here first (9051).
      result = await onRemove({
        skill_ids: skills.map((skill) => skill.id),
        detach_bindings: blockers.length > 0 && detachBindings
      });
    } catch (cause) {
      error = getErrorMessage(cause, m.organization_skills_remove_error());
      // App-run conflicts remain retryable after the job finishes; only bindings
      // require changing the selection or detaching resources first.
      if (cause instanceof EneoError && cause.code === SKILL_STILL_ATTACHED) {
        const ids: unknown = cause.response?.details?.skill_ids;
        if (Array.isArray(ids)) {
          serverBlockers = ids.filter((id): id is string => typeof id === "string");
        }
      }
      saving = false;
      return;
    }
    saving = false;
    onClose();
    await onRemoved(result);
  }

  function excludeBlockers() {
    onExclude(blockers.map((skill) => skill.id));
    error = null;
    serverBlockers = [];
  }
</script>

<AlertDialog.Root
  open
  onOpenChange={(open) => {
    if (!open && !saving) onClose();
  }}
>
  <AlertDialog.Content
    class="max-h-[calc(100dvh-2rem)] overflow-y-auto data-[size=default]:sm:max-w-lg"
  >
    <AlertDialog.Header>
      <AlertDialog.Title
        >{skills.length === 1
          ? m.organization_skills_remove_single_title()
          : m.organization_skills_remove_title({ count: String(skills.length) })}</AlertDialog.Title
      >
      <AlertDialog.Description>{m.organization_skills_remove_description()}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <ul class="max-h-64 overflow-y-auto divide-y divide-border">
      {#each skills as skill (skill.id)}
        <li class="flex flex-col gap-1 py-3 first:pt-0">
          <div class="flex flex-wrap items-center gap-2">
            <a
              href={resolve(
                `/spaces/organization/skills/${skill.id}#organization-skill-adoption-heading`
              )}
              onclick={(event) => {
                if (saving) {
                  event.preventDefault();
                  return;
                }
                restoreFocus = false;
                onClose();
              }}
              class="text-foreground min-w-0 text-sm font-medium underline underline-offset-4 [overflow-wrap:anywhere]"
            >
              {skill.display_name}
            </a>
            {#if isBlocked(skill)}
              <Badge variant="outline">{m.organization_skills_usage_in_use()}</Badge>
            {/if}
          </div>
          <p class="text-muted-foreground text-sm tabular-nums">
            {formatSkillUsage(skill.usage) ?? m.organization_skills_usage_none()}
            {#if skill.usage.personal_chat_pinned}
              · {m.organization_skills_usage_personal_chat()}{/if}
          </p>
          {#if serverBlockers.includes(skill.id)}
            <p class="text-destructive text-sm">{m.organization_skills_remove_new_binding()}</p>
          {/if}
        </li>
      {/each}
    </ul>
    {#if blockers.length > 0}
      <Alert.Root>
        <TriangleAlert aria-hidden="true" />
        <Alert.Title>
          {skills.length === 1
            ? m.organization_skills_remove_blocked_single_title()
            : m.organization_skills_remove_blocked_title()}
        </Alert.Title>
        <Alert.Description>
          {m.organization_skills_remove_blocked_description()}
          <Field.Field orientation="horizontal" class="mt-3">
            <Checkbox
              id={detachCheckboxId}
              bind:checked={detachBindings}
              disabled={saving}
              aria-describedby={`${detachCheckboxId}-description`}
            />
            <Field.Content>
              <Field.Label for={detachCheckboxId} class="text-foreground">
                {m.organization_skills_remove_detach_label()}
              </Field.Label>
              <Field.Description id={`${detachCheckboxId}-description`}>
                {m.organization_skills_remove_detach_description()}
                {#if personalChatAffected}
                  {m.organization_skills_usage_personal_chat()}.
                {/if}
              </Field.Description>
            </Field.Content>
          </Field.Field>
          {#if !detachBindings && blockers.length < skills.length}
            <div class="mt-3">
              <Button variant="outline" size="sm" onclick={excludeBlockers}>
                {m.organization_skills_remove_exclude_blocked({ count: String(blockers.length) })}
              </Button>
            </div>
          {/if}
        </Alert.Description>
      </Alert.Root>
    {/if}
    {#if error}
      <Alert.Root variant="destructive" role="alert">
        <Alert.Title>{m.organization_skills_remove_error()}</Alert.Title>
        <Alert.Description>{error}</Alert.Description>
      </Alert.Root>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={saving}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={saving || !canRemove} onclick={remove}>
        {saving
          ? m.organization_skills_removing()
          : skills.length === 1
            ? m.organization_skills_remove_action()
            : m.organization_skills_remove_confirm({ count: String(skills.length) })}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
