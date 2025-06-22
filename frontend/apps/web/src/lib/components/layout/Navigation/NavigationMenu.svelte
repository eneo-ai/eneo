<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { IconFeedback } from "@intric/icons/feedback";
  import { m } from "$lib/paraglide/messages";

  let cls: string = "";
  export { cls as class };

  const { featureFlags, environment } = getAppContext();
</script>

<nav class="{cls} flex flex-grow flex-col gap-0.5 py-3">
  <slot />
  {#if featureFlags.showHelpCenter}
    <div class="flex-grow justify-end"></div>
    <a
      href={environment.helpCenterUrl}
      target="_blank"
      rel="noreferrer"
      class="text-muted hover:bg-hover-default hover:text-primary relative flex items-center justify-center gap-3 px-[1.45rem] py-2.5 tracking-[0.008rem] hover:font-medium hover:tracking-normal"
    >
      <span>{m.have_a_question()}</span>
      <IconFeedback />
    </a>
  {/if}
</nav>
