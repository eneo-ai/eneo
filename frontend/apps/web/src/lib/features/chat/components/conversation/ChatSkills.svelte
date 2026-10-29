<!--
    The personal chat's Skills, next to Verktyg in the composer toolbar. The
    organisation's Skills run first and are read-only; for each of their own
    Skills the person chooses Av, Vid behov or Alltid. Below the composer's
    40rem breakpoint, where the toolbar is icon-only, the same choices open in
    a bottom sheet. PersonalChatSkills owns the state; a change is saved in
    the default-assistant queue, so a message sent right after uses it.
-->
<script lang="ts">
  import SkillDependencies from "$lib/features/skills/SkillDependencies.svelte";
  import { dependencySources } from "@eneo/skill-instructions";
  import { resolve } from "$app/paths";
  import { getAppContext } from "$lib/core/AppContext";
  import { getEneo } from "$lib/core/Eneo";
  import { track } from "$lib/core/helpers/track";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
  import { cn } from "$lib/utils.js";
  import { PersonalChatSkills } from "$lib/features/skills/PersonalChatSkills.svelte";
  import {
    activationModeLabel,
    personalSkillLayerMessage,
    runningPersonalChatSkills,
    type OwnSkillRow,
    type PersonalSkillMode
  } from "$lib/features/skills/personalChatSkills";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import Ban from "@lucide/svelte/icons/ban";
  import BookOpenCheck from "@lucide/svelte/icons/book-open-check";
  import CirclePause from "@lucide/svelte/icons/circle-pause";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import Lock from "@lucide/svelte/icons/lock";
  import Plus from "@lucide/svelte/icons/plus";
  import Search from "@lucide/svelte/icons/search";
  import Settings2 from "@lucide/svelte/icons/settings-2";
  import { RadioGroup as RadioGroupPrimitive, useId } from "bits-ui";
  import { untrack } from "svelte";

  const MODES: PersonalSkillMode[] = ["off", "on_demand", "always"];
  // A short list is quicker to scan than to search.
  const SEARCH_THRESHOLD = 7;

  const eneo = getEneo();
  const { user } = getAppContext();
  const {
    state: { currentSpace },
    updateDefaultAssistantSkills,
    awaitDefaultAssistantUpdates
  } = getSpacesManager();

  // Other spaces can have a default assistant too, but only the personal chat
  // takes the person's own Skills.
  const spaceId = $derived($currentSpace.personal ? $currentSpace.id : null);
  const assistantId = $derived(
    $currentSpace.personal ? ($currentSpace.default_assistant?.id ?? null) : null
  );
  const skills = $derived(
    spaceId && assistantId ? untrack(() => personalChatSkills(spaceId, assistantId)) : null
  );

  function personalChatSkills(spaceId: string, assistantId: string) {
    const assistant = { id: assistantId };
    return new PersonalChatSkills(
      {
        readConfiguration: () => eneo.skills.getAssistantConfiguration({ spaceId, assistantId }),
        listLibrary: (params) => eneo.skills.list({ spaceId, ...params }),
        save: (bindings) => updateDefaultAssistantSkills(assistant, bindings),
        settled: awaitDefaultAssistantUpdates
      },
      // Saving the personal chat's own Skills takes both.
      user.hasPermission({ allOf: ["personal_chat", "personal_skills"] })
    );
  }

  // A model change can pause the person's own Skills or resume them.
  const modelId = $derived($currentSpace.default_assistant?.completion_model?.id);
  $effect(() => {
    track(modelId);
    const owner = skills;
    if (owner) untrack(() => void owner.load());
  });
  $effect(() => {
    const owner = skills;
    return () => owner?.dispose();
  });

  const configuration = $derived(skills?.configuration ?? null);
  const organisationSkills = $derived(configuration?.organisation_bindings ?? []);
  const visible = $derived(
    skills !== null &&
      (skills.canEdit || organisationSkills.length > 0 || (configuration?.bindings.length ?? 0) > 0)
  );
  const running = $derived(configuration ? runningPersonalChatSkills(configuration) : null);
  const runningCount = $derived(running ? running.always + running.on_demand : 0);
  // No number until it is known: a 0 while loading would be wrong.
  const triggerName = $derived(
    running
      ? m.personal_chat_skills_button_label({ count: runningCount })
      : m.personal_chat_skills_button()
  );
  const layer = $derived(configuration?.personal_layer ?? null);
  const canCreate = $derived(
    (skills?.canEdit ?? false) && ($currentSpace.skill_permissions?.includes("create") ?? false)
  );

  const ownRows = $derived(skills?.ownRows ?? []);
  const helperSources = $derived.by(() => {
    const chosen = new Map(
      (skills?.bindings ?? []).map((binding) => [binding.skill_id, binding.skill_revision_id])
    );
    return dependencySources(
      (skills?.configuration?.bindings ?? []).filter(
        (binding) => chosen.get(binding.skill_id) === binding.skill_revision_id
      )
    );
  });

  const titleId = useId();
  let label = $state<HTMLElement | null>(null);
  let popoverOpen = $state(false);
  let sheetOpen = $state(false);

  function setOpen(open: boolean) {
    if (open) {
      void skills?.load({ library: true });
      // The label is hidden where the toolbar is icon-only: a bottom sheet
      // then has the room the choices need.
      if (label?.getClientRects().length === 0) {
        sheetOpen = true;
        return;
      }
    } else {
      closed();
    }
    popoverOpen = open;
  }

  function setSheetOpen(open: boolean) {
    if (!open) closed();
    sheetOpen = open;
  }

  // A refusal explains the change just made; it is old news next time.
  function closed() {
    skills?.saveErrors.clear();
  }

  function canChange(owner: PersonalChatSkills, row: OwnSkillRow) {
    return owner.canEdit && row.binding?.execution_blocked !== true;
  }

  function segmentClass(mode: PersonalSkillMode, sheet: boolean) {
    return cn(
      "text-muted-foreground focus-visible:ring-ring/50 data-[state=unchecked]:hover:text-foreground inline-flex items-center justify-center rounded-md border border-transparent px-2.5 text-xs font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-3 data-[state=checked]:font-semibold",
      sheet ? "h-11 text-sm" : "h-7",
      // Off is a neutral state; only a mode that runs takes the accent.
      mode === "off"
        ? "data-[state=checked]:border-strongest data-[state=checked]:bg-muted data-[state=checked]:text-foreground"
        : "data-[state=checked]:bg-accent-default data-[state=checked]:text-on-fill"
    );
  }
</script>

{#snippet summary()}
  <p class="text-muted-foreground text-xs">{m.personal_chat_skills_scope()}</p>
  {#if running}
    <p class="text-muted-foreground text-xs tabular-nums" aria-live="polite">
      {m.personal_chat_skills_counts({ always: running.always, on_demand: running.on_demand })}
    </p>
  {/if}
{/snippet}

{#snippet modeControl(
  owner: PersonalChatSkills,
  row: OwnSkillRow,
  sheet: boolean,
  describedBy: string
)}
  <RadioGroup.Root
    bind:value={() => row.mode, (mode) => owner.setMode(row, mode as PersonalSkillMode)}
    orientation="horizontal"
    aria-label={m.personal_chat_skills_mode_group_label({ name: row.name })}
    aria-describedby={describedBy}
    class={cn(
      "border-border bg-background auto-cols-fr grid-flow-col gap-0.5 rounded-lg border p-0.5",
      sheet ? "w-full" : "w-auto shrink-0"
    )}
  >
    {#each MODES as mode (mode)}
      <RadioGroupPrimitive.Item value={mode} class={segmentClass(mode, sheet)}>
        {activationModeLabel(mode)}
      </RadioGroupPrimitive.Item>
    {/each}
  </RadioGroup.Root>
{/snippet}

{#snippet ownSkill(owner: PersonalChatSkills, row: OwnSkillRow, sheet: boolean)}
  {@const id = `${sheet ? "sheet" : "popover"}-skill-${row.id}`}
  {@const saveError = owner.saveErrors.get(row.id)}
  <li class={sheet ? "px-4 py-3" : "px-3 py-2"}>
    <div class={sheet ? "flex flex-col gap-2" : "flex items-center gap-3"}>
      <div class="min-w-0 flex-1">
        <p class="text-foreground truncate text-sm font-medium">{row.name}</p>
        {#if helperSources.get(row.id)?.length}<p class="text-muted-foreground mt-1 text-xs">
            {m.skills_reference_used_via({ names: helperSources.get(row.id)!.join(", ") })}
          </p>{/if}
        {#if row.mode !== "off"}<SkillDependencies dependencies={row.binding?.dependencies} />{/if}
        {#if row.description}
          <p
            id="{id}-description"
            class={cn("text-muted-foreground text-xs", sheet ? "line-clamp-2" : "truncate")}
            title={row.description}
          >
            {row.description}
          </p>
        {/if}
      </div>
      {#if canChange(owner, row)}
        {@render modeControl(
          owner,
          row,
          sheet,
          row.description ? `${id}-description ${id}-status` : `${id}-status`
        )}
      {:else}
        <!-- Not the person's choice right now: the saved mode is told, not offered. -->
        <p class="text-muted-foreground shrink-0 text-xs">{activationModeLabel(row.mode)}</p>
      {/if}
    </div>
    <div id="{id}-status">
      {#if row.binding?.execution_blocked}
        <p class="text-muted-foreground mt-1 flex items-center gap-1 text-xs">
          <Ban class="size-3.5 shrink-0" aria-hidden="true" />
          {m.personal_chat_skills_blocked()}
        </p>
      {:else if row.hasNewerRevision && owner.canEdit}
        <p class="mt-1 flex flex-wrap items-center gap-x-2 text-xs">
          <span class="text-muted-foreground">{m.personal_chat_skills_update_available()}</span>
          <Button
            variant="link"
            size="xs"
            class="h-6 px-0"
            onclick={() => owner.useLatestRevision(row)}
          >
            {m.personal_chat_skills_use_latest()}
          </Button>
        </p>
      {/if}
      {#if saveError}
        <p class="text-destructive mt-1 text-xs" role="alert">{saveError}</p>
      {/if}
    </div>
  </li>
{/snippet}

{#snippet body(owner: PersonalChatSkills, sheet: boolean)}
  {@const gutter = sheet ? "px-4" : "px-3"}
  {@const loadError = owner.loadError ?? owner.library.error}
  <div class="min-h-0 flex-1 overflow-y-auto py-1">
    {#if loadError}
      <p class={cn("text-destructive flex items-center gap-2 py-2 text-xs", gutter)} role="alert">
        {loadError}
        <Button
          variant="link"
          size="xs"
          class="h-6 px-0"
          onclick={() => owner.load({ library: true })}
        >
          {m.retry()}
        </Button>
      </p>
    {/if}

    {#if !configuration}
      {#if !owner.loadError}
        <p
          class="text-muted-foreground flex items-center justify-center gap-2 py-6 text-sm"
          role="status"
        >
          <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
          {m.loading()}
        </p>
      {/if}
    {:else}
      {#if organisationSkills.length > 0}
        <div role="group" aria-labelledby="{titleId}-organisation" class="border-b pb-1">
          <p
            id="{titleId}-organisation"
            class={cn("text-muted-foreground pt-2 pb-1 text-xs font-medium", gutter)}
          >
            {m.personal_chat_skills_organisation_heading()}
          </p>
          <ul role="list">
            {#each organisationSkills as binding (binding.skill_id)}
              <li class={cn("flex items-start gap-2.5 py-2", gutter)}>
                <Lock class="text-muted-foreground mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <div class="min-w-0 flex-1">
                  <p class="text-foreground truncate text-sm font-medium">
                    {binding.display_name}
                  </p>
                  <SkillDependencies dependencies={binding.dependencies} />
                  {#if binding.description}
                    <p class="text-muted-foreground truncate text-xs" title={binding.description}>
                      {binding.description}
                    </p>
                  {/if}
                  <p class="text-muted-foreground flex flex-wrap gap-x-1 text-xs">
                    <span>
                      {binding.execution_blocked
                        ? m.personal_chat_skills_blocked()
                        : activationModeLabel(binding.activation_mode)}
                    </span>
                    <span aria-hidden="true">·</span>
                    <span>{m.personal_chat_skills_organisation_locked()}</span>
                  </p>
                </div>
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if owner.canEdit || ownRows.length > 0}
        <div role="group" aria-labelledby="{titleId}-own">
          <p
            id="{titleId}-own"
            class={cn("text-muted-foreground pt-2 pb-1 text-xs font-medium", gutter)}
          >
            {m.personal_chat_skills_own_heading()}
          </p>

          {#if layer?.status === "suspended"}
            <div class={cn("pb-2", gutter)}>
              <Alert.Root role="status">
                <CirclePause aria-hidden="true" />
                <Alert.Title>{m.personal_chat_skills_paused_title()}</Alert.Title>
                <Alert.Description>{personalSkillLayerMessage(layer)}</Alert.Description>
              </Alert.Root>
            </div>
          {/if}

          {#if owner.library.query || owner.library.items.length > SEARCH_THRESHOLD || owner.library.hasMore}
            <div class={cn("pb-1", gutter)}>
              <InputGroup.Root>
                <InputGroup.Addon>
                  <Search aria-hidden="true" />
                </InputGroup.Addon>
                <InputGroup.Input
                  value={owner.library.query}
                  type="search"
                  placeholder={m.personal_chat_skills_search()}
                  aria-label={m.personal_chat_skills_search()}
                  oninput={(event) => owner.library.setQuery(event.currentTarget.value)}
                />
              </InputGroup.Root>
            </div>
          {/if}

          {#if ownRows.length > 0}
            <ul role="list">
              {#each ownRows as row (row.id)}
                {@render ownSkill(owner, row, sheet)}
              {/each}
            </ul>
          {:else if owner.library.loading || (owner.canEdit && !owner.libraryLoaded && !loadError)}
            <p
              class="text-muted-foreground flex items-center justify-center gap-2 py-4 text-sm"
              role="status"
            >
              <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
              {m.loading()}
            </p>
          {:else if owner.library.hasMore}
            <!-- Nothing here can join the chat, but a later page may. -->
          {:else if owner.library.query}
            <p class={cn("text-muted-foreground py-3 text-sm", gutter)} role="status">
              {m.personal_chat_skills_search_empty()}
            </p>
          {:else if owner.canEdit && !loadError}
            <div class={cn("flex flex-col items-start gap-2 pt-1 pb-3", gutter)}>
              <p class="text-muted-foreground max-w-[42ch] text-sm">
                {m.personal_chat_skills_empty()}
              </p>
              {#if canCreate}
                <Button size="sm" href={resolve("/spaces/personal/skills/new")}>
                  <Plus data-icon="inline-start" aria-hidden="true" />
                  {m.skills_library_create()}
                </Button>
              {/if}
            </div>
          {/if}
          {#if owner.library.hasMore && !owner.library.loading}
            <div class={cn("py-1", gutter)}>
              <Button
                variant="ghost"
                size="sm"
                disabled={owner.library.loadingMore}
                onclick={() => owner.library.loadMore()}
              >
                {owner.library.loadingMore ? m.loading() : m.load_more()}
              </Button>
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </div>

  {#if owner.canEdit}
    <div
      class={cn(
        "border-t",
        sheet ? "grid grid-cols-2 gap-2 p-4" : "flex items-center justify-between gap-2 p-1.5"
      )}
    >
      <Button
        variant={sheet ? "outline" : "ghost"}
        size="sm"
        class={sheet ? "h-11" : undefined}
        href={resolve("/spaces/personal/skills")}
      >
        <Settings2 data-icon="inline-start" aria-hidden="true" />
        {m.personal_chat_skills_manage()}
      </Button>
      {#if canCreate && ownRows.length > 0}
        <Button
          variant={sheet ? "outline" : "ghost"}
          size="sm"
          class={sheet ? "h-11" : undefined}
          href={resolve("/spaces/personal/skills/new")}
        >
          <Plus data-icon="inline-start" aria-hidden="true" />
          {m.skills_library_create()}
        </Button>
      {/if}
    </div>
  {/if}
{/snippet}

{#if skills && visible}
  <Popover.Root bind:open={() => popoverOpen, setOpen}>
    <Popover.Trigger
      class={buttonVariants({ variant: runningCount > 0 ? "secondary" : "ghost", size: "sm" }) +
        " h-9 shrink-0 gap-1 rounded-lg px-2 @[40rem]/composer:gap-1.5 @[40rem]/composer:px-3"}
      title={triggerName}
      aria-label={triggerName}
    >
      <BookOpenCheck class="size-4" aria-hidden="true" />
      <span bind:this={label} class="hidden @[40rem]/composer:inline"
        >{m.personal_chat_skills_button()}</span
      >
      {#if running}
        <Badge
          variant={runningCount > 0 ? "default" : "outline"}
          class="hidden px-1.5 tabular-nums @[24rem]/composer:inline-flex"
          aria-hidden="true">{runningCount}</Badge
        >
      {/if}
    </Popover.Trigger>

    <Popover.Content
      side="top"
      align="start"
      aria-labelledby={titleId}
      class="flex max-h-[min(36rem,var(--bits-popover-content-available-height))] w-md max-w-[calc(100vw-1rem)] flex-col gap-0 p-0"
    >
      <div class="border-b px-3 py-2.5">
        <Popover.Title id={titleId} class="text-sm font-semibold">
          {m.personal_chat_skills_button()}
        </Popover.Title>
        {@render summary()}
      </div>
      {@render body(skills, false)}
    </Popover.Content>
  </Popover.Root>

  <Sheet.Root bind:open={() => sheetOpen, setSheetOpen}>
    <Sheet.Content
      side="bottom"
      showCloseButton={false}
      class="gap-0 rounded-t-xl p-0 data-[side=bottom]:h-[80dvh]"
    >
      <Sheet.Header class="border-b pr-24">
        <Sheet.Title>{m.personal_chat_skills_button()}</Sheet.Title>
        {@render summary()}
      </Sheet.Header>
      <Sheet.Close
        class={buttonVariants({ variant: "ghost", size: "sm" }) +
          " absolute top-2 right-2 h-11 px-3"}
      >
        {m.close()}
      </Sheet.Close>
      {@render body(skills, true)}
    </Sheet.Content>
  </Sheet.Root>
{/if}
