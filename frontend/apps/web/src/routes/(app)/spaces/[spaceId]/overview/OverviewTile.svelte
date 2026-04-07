<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import * as Card from "$lib/components/ui/card/index.js";

  let {
    title,
    count,
    href
  }: {
    title: string;
    count: number;
    href: string;
  } = $props();
</script>

<a {href} class="no-underline">
  <Card.Root class="hover:bg-hover-dimmer min-h-48 cursor-pointer transition-colors">
    <Card.Header>
      <h3 class="text-primary font-mono text-sm uppercase">{title}</h3>
    </Card.Header>
    <Card.Content class="flex flex-grow items-end justify-end">
      <span class="text-primary text-[4rem] font-bold leading-none">
        {count}
      </span>
    </Card.Content>
  </Card.Root>
</a>
