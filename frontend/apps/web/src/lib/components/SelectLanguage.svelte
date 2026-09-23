<script lang="ts">
  import * as Select from "$lib/components/ui/select/index.js";
  import { availableLanguages, type Language } from "../core/language";
  import { getLanguageStore } from "../core/language";
  import { m } from "$lib/paraglide/messages";

  const currentLanguage = getLanguageStore();

  // Language display names
  const languageLabels: Record<Language, string> = {
    sv: m.swedish(),
    en: m.english()
  };

  function selectLanguage(value: string) {
    const language = availableLanguages.find((language) => language === value);
    if (language) $currentLanguage = language;
  }
</script>

<Select.Root type="single" value={$currentLanguage} onValueChange={selectLanguage}>
  <Select.Trigger class="w-full" aria-label={m.language()}>
    {languageLabels[$currentLanguage]}
  </Select.Trigger>
  <Select.Content>
    {#each availableLanguages as language (language)}
      <Select.Item value={language} label={languageLabels[language]}>
        {languageLabels[language]}
      </Select.Item>
    {/each}
  </Select.Content>
</Select.Root>
