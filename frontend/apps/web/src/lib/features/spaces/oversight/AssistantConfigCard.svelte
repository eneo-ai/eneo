<!--
  One assistant's configuration as a tenant administrator may see it without
  being a member: settings and instructions, never questions, answers or files.
-->
<script lang="ts">
  import type { AdminSpaceAssistant } from "@eneo/eneo-js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { findHostingLabel } from "$lib/features/ai-models/hosting/hostingOptions";
  import { getCapability } from "$lib/features/mcp/capabilities";
  import { widgetStatusLabel } from "$lib/features/widget/admin/status";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { formatList } from "./format";
  import InstructionsDisclosure from "./InstructionsDisclosure.svelte";
  import type { OversightKnowledge } from "./knowledge";
  import KnowledgeRefList from "./KnowledgeRefList.svelte";

  type Props = {
    assistant: AdminSpaceAssistant;
    /** 3 under a section's h2; one level deeper where the card sits under an h3. */
    headingLevel?: 2 | 3 | 4 | 5;
    /**
     * Replaces `assistant.knowledge`, e.g. with the widget review's sources,
     * which carry document counts.
     */
    knowledge?: readonly OversightKnowledge[];
    /** Hide the web widget row, e.g. on the review of that same widget. */
    showWidget?: boolean;
  };

  let { assistant, headingLevel = 3, knowledge, showWidget = true }: Props = $props();

  const uid = $props.id();
  const headingId = `${uid}-name`;

  const model = $derived.by(() => {
    const ref = assistant.completion_model;
    if (!ref) return m.none();
    const hosting = ref.hosting ? findHostingLabel(ref.hosting) || ref.hosting.toUpperCase() : "";
    return hosting ? `${ref.name} · ${hosting}` : ref.name;
  });

  const tools = $derived([
    ...assistant.mcp_servers.map((server) => server.name),
    ...assistant.capabilities.map((purpose) => getCapability(purpose)?.label() ?? purpose)
  ]);

  const retention = $derived.by(() => {
    const days = assistant.data_retention_days;
    if (days == null) return m.admin_spaces_retention_space();
    return days === 1
      ? m.admin_spaces_retention_days_one()
      : m.admin_spaces_retention_days({ days });
  });

  const attachments = $derived(
    assistant.attachment_count === 0
      ? m.admin_spaces_none()
      : assistant.attachment_count === 1
        ? m.admin_spaces_files_one()
        : m.files({ count: assistant.attachment_count })
  );
</script>

<article
  aria-labelledby={headingId}
  class="border-default bg-primary flex min-w-0 flex-col gap-4 rounded-xl border p-4"
>
  <header class="flex flex-col gap-2">
    <div class="flex flex-wrap items-center gap-2">
      <svelte:element
        this={`h${headingLevel}`}
        id={headingId}
        class="min-w-0 text-base font-semibold break-words"
      >
        {assistant.name}
      </svelte:element>
      <Badge variant="outline">
        {assistant.published ? m.admin_spaces_published() : m.admin_spaces_unpublished()}
      </Badge>
      {#if assistant.is_default}
        <Badge variant="secondary">{m.admin_spaces_default_assistant()}</Badge>
      {/if}
    </div>
    {#if assistant.description}
      <p class="text-secondary text-sm break-words">{assistant.description}</p>
    {/if}
  </header>

  <dl class="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
    <div class="min-w-0">
      <dt class="text-secondary text-xs">{m.model()}</dt>
      <dd class="break-words">{model}</dd>
    </div>
    <div class="min-w-0">
      <dt class="text-secondary text-xs">{m.tools()}</dt>
      <dd class="break-words">{tools.length > 0 ? formatList(tools) : m.admin_spaces_none()}</dd>
    </div>
    <div class="min-w-0 sm:col-span-2">
      <dt class="text-secondary text-xs">{m.knowledge()}</dt>
      <dd><KnowledgeRefList items={knowledge ?? assistant.knowledge} /></dd>
    </div>
    <div class="min-w-0">
      <dt class="text-secondary text-xs">{m.admin_spaces_attachments()}</dt>
      <dd>{attachments}</dd>
    </div>
    <div class="min-w-0">
      <dt class="text-secondary text-xs">{m.admin_spaces_retention()}</dt>
      <dd>{retention}</dd>
    </div>
    <div class="min-w-0">
      <dt class="text-secondary text-xs">{m.insights()}</dt>
      <dd>{assistant.insight_enabled ? m.admin_spaces_insights_on() : m.admin_spaces_off()}</dd>
    </div>
    <div class="min-w-0">
      <dt class="text-secondary text-xs">{m.admin_spaces_logging()}</dt>
      <dd>{assistant.logging_enabled ? m.admin_spaces_logging_on() : m.admin_spaces_off()}</dd>
    </div>
    {#if showWidget}
      <div class="min-w-0 sm:col-span-2">
        <dt class="text-secondary text-xs">{m.admin_spaces_widget()}</dt>
        <dd class="break-words">
          {#if assistant.widget}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
            <a
              class="text-accent-stronger underline underline-offset-2"
              href={localizeHref(`/admin/widgets/${assistant.widget.id}`)}
              aria-label={m.admin_spaces_widget_review_named({ name: assistant.widget.name })}
              >{assistant.widget.name}</a
            >
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
            <span class="text-secondary">· {widgetStatusLabel(assistant.widget.status)}</span>
          {:else}
            {m.none()}
          {/if}
        </dd>
      </div>
    {/if}
  </dl>

  <InstructionsDisclosure name={assistant.name} instructions={assistant.instructions} />
</article>
