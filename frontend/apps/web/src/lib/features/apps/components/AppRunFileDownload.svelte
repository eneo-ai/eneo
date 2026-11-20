<script lang="ts">
  import type { UploadedFile } from "@eneo/eneo-js";
  import { IconDownload } from "@eneo/icons/download";
  import { toast } from "$lib/components/toast";
  import { Button } from "$lib/components/ui/button";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";

  let { file, compact = false }: { file: UploadedFile; compact?: boolean } = $props();
  const eneo = getEneo();
  let downloading = $state(false);

  async function download() {
    if (downloading) return;
    downloading = true;
    try {
      const { url } = await eneo.files.generateSignedUrl({
        fileId: file.id,
        contentDisposition: "attachment"
      });
      window.location.assign(url);
    } catch {
      toast.error(m.error_downloading_original());
    } finally {
      downloading = false;
    }
  }
</script>

<Button
  variant={compact ? "ghost" : "outline"}
  size={compact ? "icon" : "default"}
  aria-label={compact ? `${m.download()} ${file.name}` : undefined}
  onclick={download}
  disabled={downloading}
>
  <IconDownload />
  {#if !compact}{m.download()} "{file.name}"{/if}
</Button>
