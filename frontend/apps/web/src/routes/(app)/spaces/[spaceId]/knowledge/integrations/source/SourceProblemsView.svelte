<script lang="ts">
  import type { Component } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import FileBox from "@lucide/svelte/icons/file-box";
  import FileLock from "@lucide/svelte/icons/file-lock";
  import FileMinus from "@lucide/svelte/icons/file-minus";
  import FileText from "@lucide/svelte/icons/file-text";
  import FileX from "@lucide/svelte/icons/file-x";
  import Lock from "@lucide/svelte/icons/lock";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import ScanText from "@lucide/svelte/icons/scan-text";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Weight from "@lucide/svelte/icons/weight";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import CopyButton from "$lib/components/CopyButton.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import SourceProblemGroup from "$lib/features/knowledge/components/SourceProblemGroup.svelte";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import type {
    FileProblemCategory,
    FileProblemGroup,
    SourceProblems
  } from "$lib/features/integrations/sourceProblems";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    /** Null until the skipped files have loaded. */
    problems: SourceProblems | null;
    isAdmin: boolean;
    adminIntegrationsUrl: string;
    folderHref: (itemId: string) => string;
    /** The source has more than one item, so each file names its folder. */
    showFolders: boolean;
    /** Load the skipped lists again, for the items whose list could not be loaded. */
    onRetry: () => void;
  }

  let { problems, isAdmin, adminIntegrationsUrl, folderHref, showFolders, onRetry }: Props =
    $props();

  const FILES_SHOWN = 10;
  const expandedGroups = new SvelteSet<string>();

  function folderLabel(item: { name: string; folder_path?: string | null }): string {
    return item.folder_path || item.name;
  }

  const categories: Record<
    FileProblemCategory,
    { icon: Component; title: () => string; advice: () => string }
  > = {
    no_text_layer: {
      icon: ScanText,
      title: m.integration_problem_no_text_layer_title,
      advice: m.integration_problem_no_text_layer_advice
    },
    too_large: {
      icon: Weight,
      title: m.integration_problem_too_large_title,
      advice: m.integration_problem_too_large_advice
    },
    too_much_text: {
      icon: FileText,
      title: m.integration_problem_too_much_text_title,
      advice: m.integration_problem_too_much_text_advice
    },
    password_protected: {
      icon: FileLock,
      title: m.integration_problem_password_protected_title,
      advice: m.integration_problem_password_protected_advice
    },
    corrupt: {
      icon: FileX,
      title: m.integration_problem_corrupt_title,
      advice: m.integration_problem_corrupt_advice
    },
    empty: {
      icon: FileMinus,
      title: m.integration_problem_empty_title,
      advice: m.integration_problem_empty_advice
    },
    transient: {
      icon: RefreshCw,
      title: m.integration_problem_transient_title,
      advice: m.integration_problem_transient_advice
    },
    unsupported: {
      icon: FileBox,
      title: m.integration_problem_unsupported_title,
      advice: m.integration_problem_unsupported_advice
    }
  };

  let blockingCount = $derived(
    problems
      ? (problems.credentials ? 1 : 0) +
          problems.failures.reduce((sum, failure) => sum + failure.items.length, 0)
      : 0
  );
  let fixableCount = $derived(
    problems?.fixable.reduce((sum, group) => sum + group.files.length, 0) ?? 0
  );
  let intentionalCount = $derived(
    problems?.intentional.reduce((sum, group) => sum + group.files.length, 0) ?? 0
  );
  let nothingToShow = $derived(
    problems !== null &&
      blockingCount === 0 &&
      fixableCount === 0 &&
      intentionalCount === 0 &&
      problems.unavailable.length === 0
  );
</script>

{#snippet fileGroup(group: FileProblemGroup, open: boolean)}
  {@const meta = categories[group.category]}
  <SourceProblemGroup
    {open}
    title={meta.title()}
    advice={meta.advice()}
    icon={meta.icon}
    tone={group.severity === "fixable" ? "warning" : "neutral"}
    countLabel={group.files.length === 1
      ? m.integration_problem_files_one()
      : m.integration_problem_files_other({ count: group.files.length })}
  >
    {@const expanded = expandedGroups.has(group.category)}
    <ul class="flex flex-col px-4 pb-3 pl-15 text-sm">
      <!-- The same file name recurs across folders, so the key needs the position. -->
      {#each expanded ? group.files : group.files.slice(0, FILES_SHOWN) as file, index (`${index}:${file.item.id}:${file.file}`)}
        <li
          class="border-dimmer grid items-baseline gap-x-6 gap-y-0.5 border-t py-2 {showFolders
            ? 'lg:grid-cols-[minmax(0,2fr)_minmax(0,2fr)_minmax(0,3fr)]'
            : 'lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]'}"
        >
          <span class="min-w-0 font-medium break-all">{file.file}</span>
          {#if showFolders}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- href comes from the caller -->
            <a
              href={folderHref(file.item.id)}
              class="text-secondary focus-visible:ring-stronger min-w-0 justify-self-start rounded break-all hover:underline focus-visible:ring-2 focus-visible:outline-none"
              >{folderLabel(file.item)}</a
            >
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/if}
          <span class="text-secondary min-w-0">{file.detail}</span>
        </li>
      {/each}
    </ul>
    {#if group.files.length > FILES_SHOWN}
      <div class="px-4 pb-3 pl-15">
        <Button
          variant="link"
          size="sm"
          class="h-auto p-0"
          onclick={() =>
            expanded ? expandedGroups.delete(group.category) : expandedGroups.add(group.category)}
        >
          {expanded
            ? m.integration_problem_show_fewer()
            : m.integration_problem_show_all({ count: group.files.length })}
        </Button>
      </div>
    {/if}
  </SourceProblemGroup>
{/snippet}

<div class="flex flex-col gap-6">
  {#if problems === null}
    <div class="text-secondary flex items-center gap-2 text-sm" role="status">
      <IconLoadingSpinner size="sm" class="motion-safe:animate-spin" />
      <span>{m.loading()}</span>
    </div>
  {:else if nothingToShow}
    <div class="flex items-center gap-3 py-6">
      <CircleCheck class="text-positive-default size-6 shrink-0" aria-hidden="true" />
      <div class="flex flex-col">
        <p class="font-medium">{m.integration_problems_none_title()}</p>
        <p class="text-secondary text-sm">{m.integration_problems_none_description()}</p>
      </div>
    </div>
  {:else}
    {#if blockingCount > 0}
      <section aria-labelledby="problems-blocking" class="flex flex-col gap-3">
        <h2
          id="problems-blocking"
          class="text-negative-stronger text-xs font-semibold tracking-wide uppercase"
        >
          {m.integration_problems_blocking_heading({ count: blockingCount })}
        </h2>
        {#if problems.credentials}
          {@const credentials = problems.credentials}
          <div
            class="border-negative-default bg-negative-dimmer/40 flex gap-3 rounded-lg border p-4"
          >
            <span
              class="bg-negative-dimmer text-negative-stronger flex size-8 shrink-0 items-center justify-center rounded-md"
            >
              <Lock class="size-4" aria-hidden="true" />
            </span>
            <div class="flex min-w-0 flex-1 flex-col gap-1.5">
              <p class="font-medium">{m.integration_problem_credentials_title()}</p>
              <p class="text-sm">{m.integration_problem_credentials_description()}</p>
              {#if credentials.lastSyncedAt}
                <p class="text-secondary text-xs">
                  {m.integration_problem_last_successful_sync({
                    time: formatDateTime(credentials.lastSyncedAt)
                  })}
                </p>
              {/if}
              <div class="flex flex-wrap items-center gap-3 pt-1">
                <span class="text-sm">
                  <span class="font-medium">{m.integration_problem_who_fixes()}</span>
                  {m.integration_problem_who_fixes_admin()}
                </span>
                {#if isAdmin}
                  <Button size="sm" href={adminIntegrationsUrl}>
                    {m.integration_problem_open_admin()}
                  </Button>
                {:else}
                  <CopyButton
                    text={adminIntegrationsUrl}
                    label={m.integration_problem_copy_admin_link()}
                    showLabel
                    variant="outline"
                    size="sm"
                  />
                {/if}
              </div>
            </div>
          </div>
        {/if}
        {#if problems.failures.length > 0}
          <div class="grid gap-3 xl:grid-cols-2">
            {#each problems.failures as failure (failure.message)}
              <!-- A card left alone on its row takes the whole row. -->
              <div
                class="border-negative-default flex gap-3 rounded-lg border p-4 xl:last:odd:col-span-2"
              >
                <span
                  class="bg-negative-dimmer text-negative-stronger flex size-8 shrink-0 items-center justify-center rounded-md"
                >
                  <TriangleAlert class="size-4" aria-hidden="true" />
                </span>
                <div class="flex min-w-0 flex-1 flex-col gap-1.5">
                  <p class="font-medium">
                    {failure.items.length === 1
                      ? m.integration_problem_sync_failed_title({
                          name: folderLabel(failure.items[0])
                        })
                      : m.integration_problem_sync_failed_many_title({
                          count: failure.items.length
                        })}
                  </p>
                  <p class="text-sm">{m.integration_problem_sync_failed_description()}</p>
                  {#if failure.message}
                    <details class="text-secondary text-xs">
                      <summary class="cursor-pointer"
                        >{m.integration_problem_technical_details()}</summary
                      >
                      <p class="mt-1 font-mono break-words">{failure.message}</p>
                    </details>
                  {/if}
                  {#if showFolders}
                    <ul class="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                      {#each failure.items as item (item.id)}
                        <li>
                          <!-- eslint-disable svelte/no-navigation-without-resolve -- href comes from the caller -->
                          <a
                            href={folderHref(item.id)}
                            class="text-accent-default focus-visible:ring-stronger rounded font-medium hover:underline focus-visible:ring-2 focus-visible:outline-none"
                          >
                            {m.integration_problem_open_named_folder({ name: folderLabel(item) })}
                          </a>
                          <!-- eslint-enable svelte/no-navigation-without-resolve -->
                        </li>
                      {/each}
                    </ul>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </section>
    {/if}

    {#if fixableCount > 0}
      <section aria-labelledby="problems-fixable" class="flex flex-col gap-3">
        <h2
          id="problems-fixable"
          class="text-warning-stronger text-xs font-semibold tracking-wide uppercase"
        >
          {m.integration_problems_fixable_heading({ count: fixableCount })}
        </h2>
        {#if problems.skippedAsOf}
          <p class="text-secondary -mt-1 text-xs">
            {m.integration_problems_as_of({ time: formatDateTime(problems.skippedAsOf) })}
          </p>
        {/if}
        <div class="border-default overflow-hidden rounded-lg border">
          {#each problems.fixable as group, index (group.category)}
            {@render fileGroup(group, index === 0)}
          {/each}
        </div>
      </section>
    {/if}

    {#if intentionalCount > 0}
      <section aria-labelledby="problems-intentional" class="flex flex-col gap-3">
        <h2
          id="problems-intentional"
          class="text-secondary text-xs font-semibold tracking-wide uppercase"
        >
          {m.integration_problems_intentional_heading({ count: intentionalCount })}
        </h2>
        <div class="border-default overflow-hidden rounded-lg border">
          {#each problems.intentional as group (group.category)}
            {@render fileGroup(group, false)}
          {/each}
        </div>
      </section>
    {/if}

    {#if problems.notListed > 0}
      <p class="text-secondary text-sm italic">
        {m.skipped_and_n_more({ count: problems.notListed })}
      </p>
    {/if}
    {#if problems.unavailable.length > 0}
      <div class="text-secondary flex flex-wrap items-center gap-3 text-sm" role="status">
        <p>
          {m.integration_problems_unavailable({
            names: problems.unavailable.map((item) => item.name).join(", ")
          })}
        </p>
        <Button variant="outline" size="sm" onclick={onRetry}>{m.retry()}</Button>
      </div>
    {/if}
  {/if}
</div>
