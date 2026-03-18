<script lang="ts">
  export let title: string;
</script>

<section>
  <h2
    class="bg-frosted-glass-primary border-default sticky top-0 z-10 col-span-2 border-b px-6 py-4 font-mono text-[0.8125rem] font-semibold tracking-tight backdrop-blur-md lg:px-4"
  >
    {title}
  </h2>

  <div class="relative flex w-full flex-col gap-10 pt-6 pb-24 lg:px-4">
    <slot />
  </div>
</section>
