/** Every Lucide icon as data, read from the installed @lucide/svelte by plugins/lucide-icon-data.js. */
declare module "virtual:lucide-icon-data" {
  import type { IconNode } from "@lucide/svelte";

  const data: {
    /** Current icons by export name (`House`): Lucide's icon name (`house`) and SVG nodes. */
    icons: Record<string, [name: string, node: IconNode]>;
    /** Export names of renamed icons, mapped to the current one (`Home` → `House`). */
    aliases: Record<string, string>;
  };
  export default data;
}
