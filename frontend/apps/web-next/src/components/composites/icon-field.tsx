import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Button as ActionButton } from "@astryxdesign/core/Button";
import { saveUrl } from "@/features/files/signed-file-url";
import { Spinner } from "@astryxdesign/core/Spinner";
import { ImagePlus, Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { API_BASE, apiFetch } from "@/lib/api/base";
import { browserApi } from "@/lib/api/browser";
import { toast } from "@/lib/toast";

/** Uploads an image to the icons endpoint; the caller stores the id on its resource. */
export async function uploadIcon(file: File): Promise<{ id: string }> {
  const form = new FormData();
  form.append("file", file);
  const url = `${API_BASE}/api/v1/icons/`;
  const response = await apiFetch(url, { method: "POST", body: form });
  if (!response.ok) {
    throw new Error(`icon upload failed: ${response.status}`);
  }
  return (await response.json()) as { id: string };
}

/** Icon uploads are served under the API base, which authenticates the request. */
export function iconUrl(iconId: string | null | undefined): string | null {
  return iconId ? `${API_BASE}/api/v1/icons/${encodeURIComponent(iconId)}/` : null;
}

const MAX_ICON_BYTES = 256 * 1024;
const ICON_TYPES = ["image/png", "image/jpeg", "image/webp"];

function IconPreview({ url }: { url: string }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="focus-visible:outline-ring size-full focus-visible:outline-2 focus-visible:-outline-offset-2"
        aria-label={t("upload_view_avatar")}
        onClick={() => setOpen(true)}
      >
        <img src={url} alt="" className="size-full object-cover" />
      </button>
      <Dialog isOpen={open} onOpenChange={setOpen} width={560}>
        <DialogHeader title={t("upload_avatar_alt")} onOpenChange={setOpen} />
        <img
          src={url}
          alt={t("upload_avatar_preview_alt")}
          className="rounded-ax-inner mx-auto my-4 h-64 max-h-[60dvh] w-full object-contain"
        />
        <ActionButton label={t("download")} onClick={() => saveUrl(url, "icon")} />
      </Dialog>
    </>
  );
}

/**
 * Avatar upload/remove against the icons endpoint; `onSave` persists the new
 * icon id on the owning resource (assistant, group chat, ...), and the server
 * deletes the icon that id replaced.
 */
export function IconField({
  iconId,
  onSave
}: {
  iconId: string | null | undefined;
  onSave: (iconId: string | null) => Promise<unknown>;
}) {
  const t = useTranslations();
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadButton = useRef<HTMLButtonElement>(null);
  // Which button's work is running: busy, it stays enabled so it keeps focus,
  // and a second press (of either) is ignored.
  const [busy, setBusy] = useState<"upload" | "remove" | null>(null);

  const icon = iconUrl(iconId);

  async function replaceIcon(file: File) {
    if (busy) return;
    if (!ICON_TYPES.includes(file.type)) {
      toast.error(t("avatar_invalid_type"));
      return;
    }
    if (file.size > MAX_ICON_BYTES) {
      toast.error(t("avatar_too_large"));
      return;
    }
    setBusy("upload");
    let uploaded: string | undefined;
    try {
      uploaded = (await uploadIcon(file)).id;
      await onSave(uploaded);
    } catch {
      // Nothing shows an upload whose id could not be saved, and nothing else would delete it.
      if (uploaded) {
        await browserApi
          .DELETE("/api/v1/icons/{id}/", { params: { path: { id: uploaded } } })
          .catch(() => {});
      }
      toast.error(t("avatar_upload_failed"));
    } finally {
      setBusy(null);
    }
  }

  async function removeIcon() {
    if (busy) return;
    setBusy("remove");
    try {
      await onSave(null);
      // Delete goes with the icon: focus moves to Upload instead of the page.
      uploadButton.current?.focus();
    } catch {
      toast.error(t("avatar_delete_failed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <span className="bg-muted text-muted-foreground flex size-16 items-center justify-center overflow-hidden rounded-xl">
        {busy ? (
          <Spinner />
        ) : icon ? (
          <IconPreview key={icon} url={icon} />
        ) : (
          <ImagePlus className="size-6" />
        )}
      </span>
      <input
        ref={fileInput}
        type="file"
        aria-label={t("upload")}
        accept={ICON_TYPES.join(",")}
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void replaceIcon(file);
          event.target.value = "";
        }}
      />
      <Button
        ref={uploadButton}
        variant="outline"
        size="sm"
        aria-busy={busy === "upload" || undefined}
        onClick={() => {
          if (!busy) fileInput.current?.click();
        }}
      >
        {t("upload")}
      </Button>
      {iconId && (
        <Button
          variant="ghost"
          size="sm"
          aria-busy={busy === "remove" || undefined}
          onClick={() => void removeIcon()}
        >
          {busy !== "remove" && <Trash2 className="size-4" />} {t("delete")}
        </Button>
      )}
    </div>
  );
}
