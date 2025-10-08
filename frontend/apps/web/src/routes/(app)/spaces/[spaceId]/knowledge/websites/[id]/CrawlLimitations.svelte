<script lang="ts">
  import { m } from "$lib/paraglide/messages";
</script>

<div class="border-dimmer hidden border-b py-3 pr-3 lg:block">
  <div
    class="label-warning border-label-default bg-label-dimmer text-label-stronger flex items-center gap-8 rounded-lg border px-4 py-3 shadow"
  >
    <div class="flex flex-col">
      <span class="font-mono text-xs uppercase">{m.crawling()}</span>
      <span class="text-xl font-extrabold">{m.limitations()}</span>
    </div>
    <p class="-mt-[0.1rem] max-w-[105ch] pl-6 leading-[1.3rem]">
      {m.crawl_limitations_description()}
    </p>
    <div class="flex-grow"></div>
  </div>
</div>
