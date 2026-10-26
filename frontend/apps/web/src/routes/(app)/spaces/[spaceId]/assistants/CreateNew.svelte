<script lang="ts">
  import TemplateCreateDialog from "$lib/features/templates/components/TemplateCreateDialog.svelte";
  import { type Settings } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";

  let { data }: { data: { settings: Settings } } = $props();
</script>

<!-- eslint-disable-next-line @typescript-eslint/no-explicit-any -->
{#snippet triggerSnippet(props: any)}
  <Button {...props}>{m.create_assistant()}</Button>
{/snippet}
<TemplateCreateDialog kind="assistant" settings={data.settings} {triggerSnippet} />
