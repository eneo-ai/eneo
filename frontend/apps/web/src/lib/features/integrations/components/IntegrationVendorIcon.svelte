<script lang="ts">
  import { integrationData, type IntegrationType } from "../IntegrationData";

  type Props = {
    size: "sm" | "lg";
    type?: IntegrationType;
  };

  const { size, type = "confluence" }: Props = $props();
  const logoUrl = $derived.by(() => {
    return integrationData[type].logo;
  });
</script>

<img src={logoUrl} alt="" class={size === "sm" ? "w-6" : "w-12"} />
