<script lang="ts">
  import TemplateIcon from "../TemplateIcon.svelte";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { dynamicColour } from "$lib/core/colours";
  import { getTemplateController } from "../../TemplateController";

  let {
    selectTemplate,
    allTemplates,
    state: { creationMode, showCreateDialog }
  } = getTemplateController();
</script>

<div class="grid max-h-[220px] w-full grid-cols-3 gap-2 overflow-hidden p-1">
  {#each allTemplates.filter(t => t.is_default).slice(0, 3) as template (template.id)}
    <button
      onclick={(e) => {
        e.preventDefault();
        selectTemplate(template);
        $creationMode = "template";
        $showCreateDialog = true;
      }}
      {...dynamicColour({ basedOn: template.category })}
      class="rounded-2xl"
    >
      <div
        class="tile-bg border-default flex h-full flex-col gap-2.5 overflow-clip rounded-2xl border p-3 transition-all"
      >
        <TemplateIcon {template} size="large"></TemplateIcon>
        <div class="flex-grow"></div>
        <h4 class="text-dynamic-stronger line-clamp-2 text-left text-lg leading-6 font-medium">
          {formatEmojiTitle(template.name)}
        </h4>
      </div>
    </button>
  {/each}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  .tile-bg {
    background: linear-gradient(183deg, var(--dynamic-dimmer) 0%, var(--background-primary) 50%);
  }

  .tile-bg:hover {
    background: var(--dynamic-dimmer);
    @apply ring-default ring-2;
  }
</style>
