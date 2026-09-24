<script lang="ts">
  import { chart, type Config } from "./chart.js";

  export let config: Config;
  let cls = "";
  export { cls as class };
</script>

<div use:chart={config} class="h-full w-full {cls}"></div>
