<script lang="ts">
  import { browser } from "$app/environment";
  import { goto } from "$app/navigation";
  import { LoadingScreen } from "$lib/components/layout";

  export let data;

  if (browser) {
    if (data.zitadelLink) {
      window.location.href = data.zitadelLink;
    } else {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- server endpoint, not a typed route
      goto("/login");
    }
  }
</script>

<LoadingScreen></LoadingScreen>
