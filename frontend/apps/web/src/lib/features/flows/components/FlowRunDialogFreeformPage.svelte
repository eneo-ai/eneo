<script lang="ts">
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";

  let {
    freeformText,
    onInput
  }: {
    freeformText: string;
    onInput: (value: string) => void;
  } = $props();
</script>

<Field.Field>
  <Field.Label for="flow-run-freeform-input" class="text-sm font-medium">
    {m.flow_run_input()}
  </Field.Label>
  <Field.Description>{m.flow_run_input_desc()}</Field.Description>
  <Textarea
    id="flow-run-freeform-input"
    class="min-h-[14rem] font-mono text-[0.8125rem] leading-relaxed"
    value={freeformText}
    oninput={(event) => onInput(event.currentTarget.value)}
    placeholder={m.flow_run_input_placeholder()}
  />
</Field.Field>
