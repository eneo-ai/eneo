<!--
  The space's own settings as a read-only list: what it keeps, which models
  and tools it may use. Changing them stays with the space's administrators.
-->
<script lang="ts">
  import type { AdminSpaceSettings } from "@eneo/eneo-js";
  import { CAPABILITIES } from "$lib/features/mcp/capabilities";
  import { m } from "$lib/paraglide/messages";
  import { modelLabel } from "../labels";

  type Props = { settings: AdminSpaceSettings };

  let { settings }: Props = $props();

  const retention = $derived.by(() => {
    const days = settings.data_retention_days;
    if (days == null) return m.admin_spaces_retention_org();
    return days === 1
      ? m.admin_spaces_retention_days_one()
      : m.admin_spaces_retention_days({ days });
  });

  const enabled = $derived<readonly string[]>(settings.capabilities);

  const modelGroups = $derived([
    { label: m.admin_spaces_models_completion(), models: settings.completion_models },
    { label: m.admin_spaces_models_embedding(), models: settings.embedding_models },
    { label: m.admin_spaces_models_transcription(), models: settings.transcription_models }
  ]);
</script>

<section aria-labelledby="space-settings-title" class="flex flex-col gap-4">
  <h2 id="space-settings-title" class="text-lg font-semibold">{m.settings()}</h2>
  <dl
    class="border-default bg-primary grid grid-cols-1 gap-x-8 gap-y-5 rounded-lg border p-4 text-sm @2xl:grid-cols-2"
  >
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.admin_spaces_retention()}</dt>
      <dd>{retention}</dd>
    </div>
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.admin_spaces_capabilities()}</dt>
      <dd>
        <ul class="flex flex-col gap-1">
          {#each CAPABILITIES as capability (capability.purpose)}
            <li>
              {enabled.includes(capability.purpose)
                ? m.admin_spaces_capability_on({ name: capability.label() })
                : m.admin_spaces_capability_off({ name: capability.label() })}
            </li>
          {/each}
        </ul>
      </dd>
    </div>
    {#each modelGroups as group (group.label)}
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="text-secondary text-xs">{group.label}</dt>
        <dd class="wrap-anywhere">
          {#if group.models.length > 0}
            <ul class="flex flex-col gap-1">
              {#each group.models as model (model.id)}
                <li>{modelLabel(model)}</li>
              {/each}
            </ul>
          {:else}
            {m.admin_spaces_none()}
          {/if}
        </dd>
      </div>
    {/each}
    <div class="flex min-w-0 flex-col gap-1">
      <dt class="text-secondary text-xs">{m.admin_spaces_mcp()}</dt>
      <dd class="wrap-anywhere">
        {#if settings.mcp_servers.length > 0}
          <ul class="flex flex-col gap-1">
            {#each settings.mcp_servers as server (server.id)}
              <li>{server.name}</li>
            {/each}
          </ul>
        {:else}
          {m.admin_spaces_none()}
        {/if}
      </dd>
    </div>
  </dl>
</section>
