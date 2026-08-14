<script lang="ts">
  import { setContext } from "svelte";
  import { settingsDensityContext, type SettingsDensity } from "./density";

  export let title: string;
  export let description: string = "";
  export let density: SettingsDensity = "default";

  setContext(settingsDensityContext, density);
</script>

<section>
  <header
    class="border-default col-span-2 border-b px-6 lg:px-4"
    class:bg-frosted-glass-primary={density === "default"}
    class:sticky={density === "default"}
    class:top-0={density === "default"}
    class:z-10={density === "default"}
    class:py-4={density === "default"}
    class:backdrop-blur-md={density === "default"}
    class:py-3={density === "compact"}
  >
    <h2 class="text-primary text-sm font-semibold tracking-tight">{title}</h2>
    {#if description}
      <p class="text-secondary mt-1 max-w-3xl text-[0.8125rem] leading-relaxed">{description}</p>
    {/if}
  </header>

  <div
    class="relative flex w-full flex-col lg:px-4"
    class:gap-10={density === "default"}
    class:pt-6={density === "default"}
    class:pb-24={density === "default"}
    class:gap-4={density === "compact"}
    class:pt-4={density === "compact"}
    class:pb-6={density === "compact"}
  >
    <slot />
  </div>
</section>
