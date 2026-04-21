<script lang="ts">
  import { page } from "$app/stores";
  import { dynamicColour } from "$lib/core/colours";
</script>

<div {...dynamicColour({ basedOn: $page.params.appId ?? "" })} class="flex h-full w-full flex-grow">
  <slot />
</div>
