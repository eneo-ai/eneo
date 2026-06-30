<script lang="ts">
  import { IconCollections } from "@eneo/icons/collections";

  interface Props {
    name: string;
    link: string;
    itemCount?: number;
    subtitle: string;
  }

  let { name, link, subtitle }: Props = $props();
</script>

<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- link is a typed prop passed from caller -->
<a href={link} class="group flex w-full items-center gap-2">
  <div class="text-muted flex-shrink-0">
    <IconCollections class="min-w-6" />
  </div>
  <div class="min-w-0 flex-1">
    <span class="block truncate font-medium group-hover:underline">
      {name}
    </span>
    <span class="text-secondary block truncate text-xs">
      {subtitle}
    </span>
  </div>
</a>
