<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { IconLinkExternal } from "@intric/icons/link-external";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { m } from "$lib/paraglide/messages";

  const { versions } = getAppContext();

  let expanded = $state(false);
</script>

<div class="px-[1.45rem] py-2 text-xs">
  <button
    onclick={() => (expanded = !expanded)}
    class="text-muted hover:text-secondary flex w-full items-center justify-between gap-2"
  >
    <span>{m.version()}</span>
    <IconChevronDown
      size="sm"
      class="transition-transform {expanded ? 'rotate-180' : ''}"
    />
  </button>

  {#if expanded}
    <div class="text-muted mt-2 flex flex-col gap-1 font-mono text-[0.65rem]">
      <span>Frontend: {versions.frontend}</span>
      <span>Backend: {versions.backend}</span>
      <span>Client: {versions.client}</span>
      <a
        href="https://eneo.ai/versioner.html"
        target="_blank"
        rel="noreferrer"
        class="hover:text-secondary mt-1 flex items-center justify-between"
      >
        {m.read_more()}
        <IconLinkExternal size="sm" />
      </a>
    </div>
  {/if}
</div>
