"use client";

import { ImagePlus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";

async function uploadIcon(file: File): Promise<{ id: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/eneo/api/v1/icons/", { method: "POST", body: form });
  if (!response.ok) throw new Error(`icon upload failed: ${response.status}`);
  return (await response.json()) as { id: string };
}

/** Icon uploads are served through the auth-injecting proxy. */
export function iconUrl(iconId: string | null | undefined): string | null {
  return iconId ? `/api/eneo/api/v1/icons/${iconId}/` : null;
}

/**
 * Avatar upload/remove against the icons endpoint; `onSave` persists the new
 * icon id on the owning resource (assistant, group chat, ...).
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
  const [busy, setBusy] = useState(false);

  const icon = iconUrl(iconId);

  async function replaceIcon(file: File) {
    setBusy(true);
    try {
      const uploaded = await uploadIcon(file);
      await onSave(uploaded.id);
    } catch {
      toast.error(t("avatar_upload_failed"));
    } finally {
      setBusy(false);
    }
  }

  async function removeIcon() {
    setBusy(true);
    try {
      if (iconId) {
        await unwrap(
          browserApi.DELETE("/api/v1/icons/{id}/", { params: { path: { id: iconId } } })
        );
      }
      await onSave(null);
    } catch {
      toast.error(t("avatar_delete_failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <span className="bg-muted text-muted-foreground flex size-16 items-center justify-center overflow-hidden rounded-xl">
        {busy ? (
          <Spinner />
        ) : icon ? (
          // Auth-proxied backend upload; next/image cannot optimize it.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={icon} alt="" className="size-full object-cover" />
        ) : (
          <ImagePlus className="size-6" />
        )}
      </span>
      <input
        ref={fileInput}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void replaceIcon(file);
          event.target.value = "";
        }}
      />
      <Button
        variant="outline"
        size="sm"
        disabled={busy}
        onClick={() => fileInput.current?.click()}
      >
        {t("upload")}
      </Button>
      {iconId && (
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => void removeIcon()}>
          <Trash2 className="size-4" /> {t("delete")}
        </Button>
      )}
    </div>
  );
}
