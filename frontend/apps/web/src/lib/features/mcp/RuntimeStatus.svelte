<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { RuntimeDiagnostics } from "./runtimeStatus";
  import { runtimeMessages } from "./runtimeStatus";

  let { status }: { status?: RuntimeDiagnostics | null } = $props();
</script>

{#if status}
  <!-- Same right gutter as the tab content below, so the box lines up with the cards and the table. -->
  <div class="pt-6 pr-6">
    <section class="border-default rounded-xl border p-5" aria-labelledby="runtime-status-title">
      <h2 id="runtime-status-title" class="text-default font-semibold">
        {m.tools_runtime_title()}
      </h2>
      <div role="status" class="text-secondary mt-2 space-y-2 text-sm">
        {#each runtimeMessages(status) as message (message)}
          <p>{message}</p>
        {/each}
        {#if status.version}
          <p>
            {m.tools_runtime_versions({
              backend: status.expected_version,
              runtime: status.version
            })}
          </p>
        {/if}
      </div>
    </section>
  </div>
{/if}
