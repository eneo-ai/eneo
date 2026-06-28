<script lang="ts">
  import TemplateIcon from "../TemplateIcon.svelte";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { Button, Dialog } from "@eneo/ui";
  import { dynamicColour } from "$lib/core/colours";
  import { getTemplateController } from "../../TemplateController";
  import TemplateLanguageSwitcher from "./TemplateLanguageSwitcher.svelte";
  import { m } from "$lib/paraglide/messages";
  import { BookOpen, FileUp, Check } from "lucide-svelte";

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
      <div class="flex items-center justify-between px-8 pt-8 pb-6">
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
          class="flex w-full flex-col gap-1.5 px-6 pt-4 pb-1 last-of-type:pb-4"
        >
          <!-- Category Header with Count Badge -->
          <div class="border-border-dimmer flex items-center gap-3 border-b px-2 pb-2">
            <h3 id="category-{idx}" class="flex-1 text-base font-semibold">
              {section.title}
            </h3>
            <span class="text-muted text-xs tabular-nums">
              {section.templates.length}
              {section.templates.length === 1 ? m.template_singular() : m.template_plural()}
            </span>
          </div>

          <!-- Responsive Template Grid -->
          <div
            role="listbox"
            aria-label={section.title}
            class="grid w-full grid-cols-1 gap-3 px-2 pt-1 sm:grid-cols-2 lg:grid-cols-3"
          >
            {#each section.templates as template (template.id)}
              {@const isSelected = template.id === currentlySelected?.id}
              {@const hasKnowledge = !!template.wizard?.collections}
              {@const hasAttachments = !!template.wizard?.attachments}
              {@const hasDescription = !!template.description}
              {@const hasMetadata = hasKnowledge || hasAttachments}
              {@const isCompact = !hasDescription && !hasMetadata}
              <button
                role="option"
                aria-selected={isSelected}
                aria-label={formatEmojiTitle(template.name)}
                on:click|preventDefault={() => {
                  currentlySelected = template;
                }}
                {...dynamicColour({ basedOn: template.category })}
                type="button"
                class="focus-visible:ring-accent-default rounded-xl transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                data-selected={isSelected}
              >
                <div
                  class="tile-bg border-default relative flex h-full flex-col overflow-clip rounded-xl border transition-[background,border-color,box-shadow] duration-150 {isCompact
                    ? 'gap-0 p-3'
                    : 'gap-2.5 p-4'}"
                >
                  {#if isSelected}
                    <span class="absolute top-2.5 right-2.5">
                      <Check class="text-accent-default h-5 w-5" strokeWidth={2.5} />
                    </span>
                  {/if}
                  {#if template.is_default}
                    <span
                      class="absolute top-2.5 {isSelected
                        ? 'right-9'
                        : 'right-2.5'} bg-positive-stronger/10 text-positive-stronger border-positive-stronger/20 rounded-full border px-2 py-0.5 text-xs font-medium"
                    >
                      {m.default_model()}
                    </span>
                  {/if}
                  <div class="flex w-full items-center gap-2.5">
                    <TemplateIcon {template}></TemplateIcon>
                    <h4 class="text-dynamic-stronger line-clamp-1 text-left text-sm font-semibold">
                      {formatEmojiTitle(template.name)}
                    </h4>
                  </div>
                  {#if hasDescription}
                    <p class="text-muted line-clamp-2 w-full text-left text-xs leading-relaxed">
                      {template.description}
                    </p>
                  {/if}
                  {#if hasMetadata}
                    <div class="flex items-center gap-3 pt-0.5">
                      {#if hasKnowledge}
                        <span class="text-muted flex items-center gap-1 text-xs">
                          <BookOpen class="h-3 w-3" />
                          {m.wizard_collections_section()}
                        </span>
                      {/if}
                      {#if hasAttachments}
                        <span class="text-muted flex items-center gap-1 text-xs">
                          <FileUp class="h-3 w-3" />
                          {m.wizard_attachments_section()}
                        </span>
                      {/if}
                    </div>
                  {/if}
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
        class="w-fit min-w-[10rem]"
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
  @reference "@eneo/ui/styles";
  button[data-selected="true"] {
    @apply focus:outline-offset-4;
  }

  button[data-selected="true"] > div {
    @apply border-accent-default shadow-accent-dimmer/50 outline-accent-default shadow-md outline outline-1;
  }

  .tile-bg {
    background: linear-gradient(183deg, var(--dynamic-dimmer) 0%, var(--background-primary) 50%);
  }

  button[data-selected="true"] .tile-bg {
    background: linear-gradient(175deg, var(--dynamic-dimmer) 0%, var(--accent-dimmer) 60%);
  }

  .tile-bg:hover {
    background: var(--dynamic-dimmer);
    @apply ring-default ring-1;
  }
</style>
