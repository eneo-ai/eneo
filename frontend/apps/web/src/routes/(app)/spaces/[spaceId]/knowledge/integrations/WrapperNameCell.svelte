<script lang="ts">
  import { IconCollections } from "@intric/icons/collections";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    name: string;
    link: string;
    itemCount: number;
    subtitle: string;
  }

  let { name, link, itemCount, subtitle }: Props = $props();

  let itemCountLabel = $derived(
    itemCount === 1
      ? m.wrapper_items_count_one({ count: itemCount })
      : m.wrapper_items_count_other({ count: itemCount })
  );
</script>

<a href={link} class="flex w-full items-center gap-2 group">
  <div class="text-muted flex-shrink-0">
    <IconCollections class="min-w-6" />
  </div>
  <div class="min-w-0 flex-1">
    <span class="truncate block font-medium group-hover:underline">
      {name}
    </span>
    <span class="truncate block text-xs text-secondary">
      {subtitle}
    </span>
  </div>
</a>
