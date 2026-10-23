<script lang="ts">
  import { integrationData, type IntegrationType } from "../IntegrationData";

  type Props = {
    size: "sm" | "md" | "lg";
    type?: IntegrationType;
  };

  const { size, type = "confluence" }: Props = $props();
  const logoUrl = $derived.by(() => {
    return integrationData[type].logo;
  });
  const widths = { sm: "w-6", md: "w-8", lg: "w-12" };
</script>

<img src={logoUrl} alt="" class="shrink-0 {widths[size]}" />
