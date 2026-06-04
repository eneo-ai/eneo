<script lang="ts">
  import { Dialog, Button } from "@intric/ui";
  import type { IntegrationImportDialogProps } from "../IntegrationData";

  let { goBack, openController }: IntegrationImportDialogProps = $props();
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="small">
    <Dialog.Title>Website integrations are configured from account or admin settings</Dialog.Title>
    <Dialog.Section>
      <p class="text-secondary p-4 text-sm">
        Sitemap-backed website integrations create website knowledge sources directly and are not
        imported through this dialog.
      </p>
    </Dialog.Section>
    <Dialog.Controls>
      <Button onclick={goBack}>Back</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
