<script lang="ts">
  import { Tabs } from "bits-ui";

  export let id: string;
</script>

<Tabs.Content value={id} class="relative min-h-full w-full">
  <slot />
</Tabs.Content>
