<script lang="ts">
  import TemplateIcon from "../TemplateIcon.svelte";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { Button, Dialog } from "@intric/ui";
  import { dynamicColour } from "$lib/core/colours";
  import { getTemplateController } from "../../TemplateController";
  import TemplateLanguageSwitcher from "./TemplateLanguageSwitcher.svelte";
  import { m } from "$lib/paraglide/messages";

  let {
    getCategorisedTemplates,
    selectTemplate,
    resourceName,
    state: { showTemplateGallery, selectedTemplate }
  } = getTemplateController();
  const sections = getCategorisedTemplates();

  let currentlySelected = $selectedTemplate;
</script>

<Dialog.Root openController={showTemplateGallery}>
  <Dialog.Content width="large">
    <Dialog.Section class="mt-2">
      <!-- Dialog Header -->
      <div class="flex items-center justify-between px-10 pt-12 pb-10">
        <div class="flex w-full flex-col">
          <h2 class="px-4 pb-1 text-2xl font-bold">{m.select_a_template()}</h2>
          <p class="text-secondary max-w-[50ch] px-4">
            {m.get_started_with_template({ resourceName: resourceName.singular })}
          </p>
        </div>
        <TemplateLanguageSwitcher></TemplateLanguageSwitcher>
      </div>

      <!-- Template Gallery with Responsive Grid -->
      {#each sections as section, idx (section.title)}
        <section
          role="group"
          aria-labelledby="category-{idx}"
          class="flex w-full flex-col gap-2 p-6 pb-2 last-of-type:pb-6"
        >
          <!-- Category Header with Count Badge -->
          <div class="flex items-center gap-3 px-8 pb-3 border-b border-border-dimmer">
            <h3 id="category-{idx}" class="flex-1 text-lg font-medium">
              {section.title}
            </h3>
            <span class="inline-flex items-center px-3 py-1 rounded-full bg-bg-tertiary text-sm text-text-secondary">
              {section.templates.length} {section.templates.length === 1 ? m.template_singular() : m.template_plural()}
            </span>
          </div>

          <!-- Responsive Template Grid -->
          <div class="grid w-full grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-5 lg:gap-6 px-2">
            {#each section.templates as template (template.id)}
              {@const isSelected = template.id === currentlySelected?.id}
              <button
                role="option"
                aria-selected={isSelected}
                on:click|preventDefault={() => {
                  currentlySelected = template;
                }}
                {...dynamicColour({ basedOn: template.category })}
                type="button"
                class="rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:ring-offset-2 transition-colors duration-150"
                data-selected={isSelected}
              >
                <div
                  class="tile-bg border-default flex h-full min-h-[180px] flex-col gap-4 overflow-clip rounded-2xl border p-6 transition-all"
                >
                  <div class="flex w-full items-center gap-3">
                    <TemplateIcon {template}></TemplateIcon>
                    <h4 class="text-dynamic-stronger text-left text-base font-medium line-clamp-2">
                      {formatEmojiTitle(template.name)}
                    </h4>
                  </div>
                  <p class="w-full flex-grow text-left text-sm line-clamp-3">
                    {template.description}
                  </p>
                </div>
              </button>
            {/each}
          </div>
        </section>
      {/each}
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button
        on:click={() => {
          $showTemplateGallery = false;
        }}>{m.cancel()}</Button
      >
      <Button
        is={close}
        variant="primary"
        class="w-40"
        disabled={currentlySelected === null}
        on:click={() => {
          if (currentlySelected) {
            selectTemplate(currentlySelected);
          }
        }}>{m.choose_template()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<style lang="postcss">
  @reference "@intric/ui/styles";
  button[data-selected="true"] {
    @apply focus:outline-offset-4;
  }

  button[data-selected="true"] > div {
    @apply border-accent-default shadow-accent-dimmer outline-accent-default shadow-md outline;
  }

  .tile-bg {
    background: linear-gradient(183deg, var(--dynamic-dimmer) 0%, var(--background-primary) 50%);
  }

  button[data-selected="true"] .tile-bg {
    background: linear-gradient(183deg, var(--dynamic-dimmer) 0%, var(--accent-dimmer) 50%);
  }

  .tile-bg:hover {
    background: var(--dynamic-dimmer);
    @apply ring-default ring-2;
  }
</style>
