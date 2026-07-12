<script lang="ts">
  import { EneoError, type Flow, type Eneo } from "@eneo/eneo-js";
  import {
    AlertTriangle,
    CheckCircle2,
    Download,
    Loader2,
    Minus,
    PackageOpen
  } from "lucide-svelte";
  import { toast } from "$lib/components/toast";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import {
    defaultFlowPackageId,
    downloadFlowPackageFile,
    mapFlowPackageExportError
  } from "$lib/features/flows/flowPackageTransfer";
  import { m } from "$lib/paraglide/messages";

  let {
    flow,
    eneo,
    beforeExport
  }: {
    flow: Flow;
    eneo: Eneo;
    beforeExport?: () => Promise<void>;
  } = $props();

  let open = $state(false);
  let packageId = $state("");
  let packageVersion = $state("1.0.0");
  let packageName = $state("");
  let packageDescription = $state("");
  let packageIdManuallyEdited = $state(false);
  let exportError = $state<string | null>(null);
  let exporting = $state(false);

  const trimmedId = $derived(packageId.trim());
  const trimmedVersion = $derived(packageVersion.trim());
  const trimmedName = $derived(packageName.trim());

  const stepCount = $derived(flow.steps?.length ?? 0);
  const canSubmit = $derived(
    trimmedId.length > 0 && trimmedVersion.length > 0 && trimmedName.length > 0 && !exporting
  );

  function handleOpenChange(next: boolean) {
    if (next) {
      packageId = defaultFlowPackageId(flow.name);
      packageVersion = "1.0.0";
      packageName = flow.name;
      packageDescription = flow.description ?? "";
      packageIdManuallyEdited = false;
      exportError = null;
    }
    open = next;
  }

  function onPackageIdInput(event: Event) {
    packageIdManuallyEdited = true;
    packageId = (event.currentTarget as HTMLInputElement).value;
  }

  function onNameInput(event: Event) {
    const next = (event.currentTarget as HTMLInputElement).value;
    packageName = next;
    if (!packageIdManuallyEdited) {
      packageId = defaultFlowPackageId(next);
    }
  }

  function stepCountLabel(count: number): string {
    if (count === 1) return m.flow_package_export_step_count_singular();
    return m.flow_package_export_step_count({ count: String(count) });
  }

  async function exportPackage() {
    exporting = true;
    exportError = null;
    try {
      await beforeExport?.();
      const response = await eneo.flows.packages.export({
        id: flow.id,
        packageId: trimmedId,
        packageVersion: trimmedVersion,
        name: trimmedName,
        description: packageDescription.trim()
      });
      downloadFlowPackageFile(response, "flow-package.eneopkg");
      toast.success(m.flow_package_export_success());
      open = false;
    } catch (error) {
      const message =
        mapFlowPackageExportError(error) ??
        (error instanceof EneoError ? error.getReadableMessage() : String(error));
      exportError = m.flow_package_export_failed({ message });
    } finally {
      exporting = false;
    }
  }
</script>

<Button variant="outline" onclick={() => handleOpenChange(true)}>
  <Download class="size-4" />
  {m.flow_package_export_button()}
</Button>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
  <Dialog.Content
    class="grid max-h-[92vh] !max-w-2xl grid-rows-[auto_minmax(0,1fr)_auto] !gap-0 overflow-hidden !p-0"
  >
    <header class="border-default flex items-start gap-3 border-b px-5 py-4 sm:px-6 sm:py-5">
      <div
        class="bg-accent-default/10 text-accent-default flex size-10 shrink-0 items-center justify-center rounded-xl"
        aria-hidden="true"
      >
        <PackageOpen class="size-5" />
      </div>
      <div class="min-w-0 flex-1">
        <Dialog.Title class="text-primary text-base font-semibold tracking-tight">
          {m.flow_package_export()}
        </Dialog.Title>
        <Dialog.Description class="text-secondary mt-1 max-w-[64ch] text-sm leading-relaxed">
          {m.flow_package_export_description()}
        </Dialog.Description>
      </div>
    </header>

    <div class="overflow-y-auto px-5 py-5 sm:px-6">
      <div class="flex flex-col gap-6">
        <section class="flex flex-col gap-4">
          <h3 class="text-muted text-xs font-semibold tracking-wide uppercase">
            {m.flow_package_export_section_identity()}
          </h3>
          <Field.Group>
            <Field.Field>
              <Field.Label for="flow-package-export-id">
                {m.flow_package_package_id()}
              </Field.Label>
              <Field.Description>{m.flow_package_package_id_help()}</Field.Description>
              <Input
                id="flow-package-export-id"
                value={packageId}
                oninput={onPackageIdInput}
                disabled={exporting}
                autocomplete="off"
                spellcheck={false}
              />
            </Field.Field>

            <Field.Field>
              <Field.Label for="flow-package-export-version">
                {m.flow_package_package_version()}
              </Field.Label>
              <Field.Description>{m.flow_package_package_version_help()}</Field.Description>
              <Input
                id="flow-package-export-version"
                bind:value={packageVersion}
                disabled={exporting}
                autocomplete="off"
                spellcheck={false}
              />
            </Field.Field>
          </Field.Group>
        </section>

        <section class="flex flex-col gap-4">
          <h3 class="text-muted text-xs font-semibold tracking-wide uppercase">
            {m.flow_package_export_section_presentation()}
          </h3>
          <Field.Group>
            <Field.Field>
              <Field.Label for="flow-package-export-name">{m.flow_package_name()}</Field.Label>
              <Input
                id="flow-package-export-name"
                value={packageName}
                oninput={onNameInput}
                disabled={exporting}
              />
            </Field.Field>

            <Field.Field>
              <Field.Label for="flow-package-export-description">
                {m.flow_package_package_description()}
              </Field.Label>
              <Textarea
                id="flow-package-export-description"
                bind:value={packageDescription}
                disabled={exporting}
                rows={4}
              />
            </Field.Field>
          </Field.Group>
        </section>

        <Card.Root>
          <Card.Content class="grid gap-3 p-4 sm:p-5">
            <div>
              <h3 class="text-primary text-sm font-semibold tracking-tight">
                {m.flow_package_export_contents_title()}
              </h3>
              {#if stepCount > 0}
                <p class="text-secondary mt-1 text-sm">
                  {stepCountLabel(stepCount)}
                </p>
              {/if}
            </div>
            <ul class="flex flex-col gap-2 text-sm">
              <li class="flex items-start gap-2">
                <CheckCircle2
                  class="text-positive-stronger mt-0.5 size-4 shrink-0"
                  aria-hidden="true"
                />
                <span class="text-secondary leading-relaxed">
                  {m.flow_package_export_contents_includes()}
                </span>
              </li>
              <li class="flex items-start gap-2">
                <Minus class="text-muted mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <span class="text-muted leading-relaxed">
                  {m.flow_package_export_contents_excludes()}
                </span>
              </li>
            </ul>
          </Card.Content>
        </Card.Root>

        {#if exportError}
          <Alert.Root variant="destructive">
            <AlertTriangle class="size-4" />
            <Alert.Title>{m.error()}</Alert.Title>
            <Alert.Description>{exportError}</Alert.Description>
          </Alert.Root>
        {/if}
      </div>
    </div>

    <div
      class="border-default bg-background flex flex-col-reverse gap-2 border-t px-5 py-3.5 sm:flex-row sm:justify-end sm:px-6"
    >
      <Button variant="outline" onclick={() => handleOpenChange(false)} disabled={exporting}>
        {m.cancel()}
      </Button>
      <Button onclick={exportPackage} disabled={!canSubmit}>
        {#if exporting}
          <Loader2 class="size-4 animate-spin" />
          {m.flow_package_exporting()}
        {:else}
          <Download class="size-4" />
          {m.flow_package_export_button()}
        {/if}
      </Button>
    </div>
  </Dialog.Content>
</Dialog.Root>
