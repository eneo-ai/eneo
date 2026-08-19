<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";

  interface Props {
    open: boolean;
    /** Create writes a new draft flow; edit writes into an existing one. */
    mode: "create" | "edit";
    stepCount: number;
    onconfirm: () => void;
  }

  let { open = $bindable(false), mode, stepCount, onconfirm }: Props = $props();

  const isCreate = $derived(mode === "create");
</script>

<AlertDialog.Root bind:open>
  <AlertDialog.Content class="max-w-[28.75rem]">
    <AlertDialog.Header>
      <AlertDialog.Title>
        {isCreate ? m.ai_builder_approve_dialog_title() : m.ai_builder_approve_dialog_title_edit()}
      </AlertDialog.Title>
      <AlertDialog.Description>
        {isCreate ? m.ai_builder_approve_dialog_body() : m.ai_builder_approve_dialog_body_edit()}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <ul class="text-secondary flex list-none flex-col gap-1.5 p-0 text-[0.8125rem]">
      <li>
        {isCreate
          ? m.ai_builder_approve_dialog_steps({ count: stepCount })
          : m.ai_builder_approve_dialog_steps_edit({ count: stepCount })}
      </li>
      <li>{m.ai_builder_approve_dialog_no_data()}</li>
      <li>{m.ai_builder_approve_dialog_step_editable()}</li>
    </ul>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.ai_builder_approve_dialog_cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action onclick={onconfirm}>
        {isCreate
          ? m.ai_builder_approve_dialog_confirm()
          : m.ai_builder_approve_dialog_confirm_edit()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
