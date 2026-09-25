<!--
  How the space's assistants, apps and group chats are set up, down to their
  instructions, but never what anyone asked them or which files they got.
-->
<script lang="ts">
  import type { AdminSpaceApp, AdminSpaceAssistant, AdminSpaceGroupChat } from "@eneo/eneo-js";
  import { Lock } from "@lucide/svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import AssistantConfigCard from "$lib/features/spaces/oversight/AssistantConfigCard.svelte";
  import InstructionsDisclosure from "$lib/features/spaces/oversight/InstructionsDisclosure.svelte";
  import { m } from "$lib/paraglide/messages";
  import { modelLabel } from "../labels";

  type Props = {
    assistants: readonly AdminSpaceAssistant[];
    apps: readonly AdminSpaceApp[];
    groupChats: readonly AdminSpaceGroupChat[];
  };

  let { assistants, apps, groupChats }: Props = $props();

  const uid = $props.id();
  const number = new Intl.NumberFormat(intlLocale());

  function runRetention(app: AdminSpaceApp) {
    const days = app.data_retention_days;
    if (days == null) return m.admin_spaces_retention_space();
    return days === 1
      ? m.admin_spaces_retention_days_one()
      : m.admin_spaces_retention_days({ days });
  }

  function assistantCount(chat: AdminSpaceGroupChat) {
    return chat.assistant_count === 1
      ? m.admin_spaces_count_assistants_one()
      : m.admin_spaces_count_assistants({ count: number.format(chat.assistant_count) });
  }
</script>

<div class="flex flex-col gap-10">
  <section aria-labelledby={`${uid}-assistants`} class="flex flex-col gap-4">
    <h2 id={`${uid}-assistants`} class="text-lg font-semibold">{m.assistants()}</h2>
    <p class="text-secondary flex items-start gap-2 text-sm">
      <Lock class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      {m.admin_spaces_content_note()}
    </p>
    {#if assistants.length > 0}
      <ul class="grid gap-4 @5xl:grid-cols-2">
        {#each assistants as assistant (assistant.id)}
          <li class="min-w-0"><AssistantConfigCard {assistant} /></li>
        {/each}
      </ul>
    {:else}
      <p class="text-secondary text-sm">{m.admin_spaces_no_assistants()}</p>
    {/if}
  </section>

  <section aria-labelledby={`${uid}-apps`} class="flex flex-col gap-4">
    <h2 id={`${uid}-apps`} class="text-lg font-semibold">{m.apps()}</h2>
    {#if apps.length > 0}
      <ul class="grid gap-4 @5xl:grid-cols-2">
        {#each apps as app (app.id)}
          <li class="min-w-0">
            <!-- The same card as an assistant's, with the fields an app has. -->
            <article
              aria-labelledby={`${uid}-app-${app.id}`}
              class="border-default bg-primary flex min-w-0 flex-col gap-4 rounded-xl border p-4"
            >
              <header class="flex flex-col gap-2">
                <div class="flex flex-wrap items-center gap-2">
                  <h3
                    id={`${uid}-app-${app.id}`}
                    class="min-w-0 text-base font-semibold wrap-anywhere"
                  >
                    {app.name}
                  </h3>
                  <Badge variant="outline">
                    {app.published ? m.admin_spaces_published() : m.admin_spaces_unpublished()}
                  </Badge>
                </div>
                {#if app.description}
                  <p class="text-secondary text-sm wrap-anywhere">{app.description}</p>
                {/if}
              </header>
              <dl class="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                <div class="min-w-0">
                  <dt class="text-secondary text-xs">{m.model()}</dt>
                  <dd class="wrap-anywhere">
                    {app.completion_model ? modelLabel(app.completion_model) : m.none()}
                  </dd>
                </div>
                <div class="min-w-0">
                  <dt class="text-secondary text-xs">{m.admin_spaces_transcription_model()}</dt>
                  <dd class="wrap-anywhere">
                    {app.transcription_model ? modelLabel(app.transcription_model) : m.none()}
                  </dd>
                </div>
                <div class="min-w-0">
                  <dt class="text-secondary text-xs">{m.admin_spaces_retention_runs()}</dt>
                  <dd>{runRetention(app)}</dd>
                </div>
              </dl>
              <InstructionsDisclosure name={app.name} instructions={app.instructions} />
            </article>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="text-secondary text-sm">{m.admin_spaces_no_apps()}</p>
    {/if}
  </section>

  <section aria-labelledby={`${uid}-group-chats`} class="flex flex-col gap-4">
    <h2 id={`${uid}-group-chats`} class="text-lg font-semibold">
      {m.admin_spaces_group_chats()}
    </h2>
    {#if groupChats.length > 0}
      <div class="border-default bg-primary overflow-hidden rounded-lg border">
        <Table.Root
          class="[&_td]:px-3 [&_td]:py-3 [&_td]:align-top [&_td]:whitespace-normal [&_th]:px-3 [&_th]:whitespace-normal @3xl:[&_td]:px-4 @3xl:[&_th]:px-4"
        >
          <Table.Caption class="sr-only">{m.admin_spaces_group_chats_caption()}</Table.Caption>
          <Table.Header>
            <Table.Row>
              <Table.Head scope="col">{m.name()}</Table.Head>
              <Table.Head scope="col">{m.status()}</Table.Head>
              <Table.Head scope="col" class="hidden @xl:table-cell">{m.assistants()}</Table.Head>
              <Table.Head scope="col" class="hidden @xl:table-cell">{m.insights()}</Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each groupChats as chat (chat.id)}
              <Table.Row>
                <th scope="row" class="py-3 text-left align-top font-medium">
                  <span class="block wrap-anywhere">{chat.name}</span>
                  <span class="text-secondary block text-xs font-normal @xl:hidden">
                    {assistantCount(chat)} · {m.admin_spaces_insights_state({
                      state: chat.insight_enabled ? m.admin_spaces_on() : m.admin_spaces_off()
                    })}
                  </span>
                </th>
                <Table.Cell>
                  {chat.published ? m.admin_spaces_published() : m.admin_spaces_unpublished()}
                </Table.Cell>
                <Table.Cell class="hidden tabular-nums @xl:table-cell">
                  {number.format(chat.assistant_count)}
                </Table.Cell>
                <Table.Cell class="hidden @xl:table-cell">
                  {chat.insight_enabled ? m.admin_spaces_on() : m.admin_spaces_off()}
                </Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>
    {:else}
      <p class="text-secondary text-sm">{m.admin_spaces_no_group_chats()}</p>
    {/if}
  </section>
</div>
