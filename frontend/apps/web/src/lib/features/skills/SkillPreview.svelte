<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { SkillBindingPreview } from "./skillBindingCatalog";

  let { preview }: { preview: SkillBindingPreview } = $props();
</script>

<div class="flex min-w-0 flex-col gap-5">
  <div class="flex flex-wrap items-center gap-2">
    <Badge variant="secondary">
      {preview.source === "organization" ? m.skills_source_organization() : m.skills_source_space()}
    </Badge>
    <Badge variant="outline">
      {m.skills_revision_label({ revision: String(preview.revisionNumber) })}
    </Badge>
    <span class="text-muted-foreground min-w-0 truncate font-mono text-xs">{preview.slug}</span>
  </div>

  <div>
    <h3 class="text-sm font-medium">{m.description()}</h3>
    <p class="text-muted-foreground mt-1 max-w-[75ch] text-sm leading-6 break-words">
      {preview.description}
    </p>
  </div>

  <div>
    <h3 class="text-sm font-medium">{m.instructions()}</h3>
    <pre
      class="border-border bg-muted/30 mt-2 rounded-md border p-4 text-sm leading-6 whitespace-pre-wrap [overflow-wrap:anywhere]"><code
        >{preview.instructions}</code
      ></pre>
  </div>
</div>
