<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { RuntimeDiagnostics } from "./runtimeStatus";
  import { runtimeMessages } from "./runtimeStatus";

  let { status }: { status?: RuntimeDiagnostics | null } = $props();
</script>

{#if status}
  <section
    class="mx-auto my-4 w-full max-w-5xl rounded-lg border p-4"
    aria-labelledby="runtime-status-title"
  >
    <h2 id="runtime-status-title" class="font-medium">{m.tools_runtime_title()}</h2>
    <div role="status" class="mt-2 space-y-2 text-sm text-secondary">
      {#each runtimeMessages(status) as message (message)}
        <p>{message}</p>
      {/each}
      {#if status.version}
        <p>
          {m.tools_runtime_versions({ backend: status.expected_version, runtime: status.version })}
        </p>
      {/if}
    </div>
  </section>
{/if}
