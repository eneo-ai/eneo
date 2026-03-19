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
          <div class="border-border-dimmer flex items-center gap-3 border-b px-8 pb-3">
            <h3 id="category-{idx}" class="flex-1 text-lg font-medium">
              {section.title}
            </h3>
            <span
              class="bg-bg-tertiary text-text-secondary inline-flex items-center rounded-full px-3 py-1 text-sm"
            >
              {section.templates.length}
              {section.templates.length === 1 ? m.template_singular() : m.template_plural()}
            </span>
          </div>

          <!-- Responsive Template Grid -->
          <div
            class="grid w-full grid-cols-1 gap-4 px-2 sm:grid-cols-2 sm:gap-5 lg:grid-cols-3 lg:gap-6"
          >
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
                class="focus-visible:ring-accent-default rounded-2xl transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                data-selected={isSelected}
              >
                <div
                  class="tile-bg border-default relative flex h-full min-h-[180px] flex-col gap-4 overflow-clip rounded-2xl border p-6 transition-all"
                >
                  {#if template.is_default}
                    <span
                      class="bg-positive-stronger/10 text-positive-stronger border-positive-stronger/20 absolute top-2 right-2 rounded-full border px-2 py-0.5 text-xs font-medium"
                    >
                      {m.default_model()}
                    </span>
                  {/if}
                  <div class="flex w-full items-center gap-3">
                    <TemplateIcon {template}></TemplateIcon>
                    <h4 class="text-dynamic-stronger line-clamp-2 text-left text-base font-medium">
                      {formatEmojiTitle(template.name)}
                    </h4>
                  </div>
                  <p class="line-clamp-3 w-full flex-grow text-left text-sm">
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
