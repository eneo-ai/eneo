<script lang="ts">
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import type { IntegrationType } from "$lib/features/integrations/IntegrationData";

  interface Props {
    name: string;
    integrationType: IntegrationType;
    href: string;
    subtitle: string;
  }

  let { name, integrationType, href, subtitle }: Props = $props();
</script>

<div class="flex min-w-0 items-center gap-3">
  <IntegrationVendorIcon size="md" type={integrationType}></IntegrationVendorIcon>
  <div class="flex min-w-0 flex-col">
    <!-- eslint-disable svelte/no-navigation-without-resolve -- link is a typed prop passed from caller -->
    <a
      {href}
      class="focus-visible:ring-stronger truncate rounded font-medium hover:underline focus-visible:ring-2 focus-visible:outline-none"
    >
      {name}
    </a>
    <!-- eslint-enable svelte/no-navigation-without-resolve -->
    <span class="text-secondary truncate text-xs">{subtitle}</span>
  </div>
</div>
