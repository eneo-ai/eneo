"use client";

import { ImagePlus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { iconUrl } from "../assistants";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

function SaveRow({
  dirty,
  pending,
  onSave,
  onRevert
}: {
  dirty: boolean;
  pending: boolean;
  onSave: () => void;
  onRevert: () => void;
}) {
  const t = useTranslations();
  if (!dirty) return null;
  return (
    <div className="flex justify-end gap-2">
      <Button variant="outline" size="sm" disabled={pending} onClick={onRevert}>
        {t("cancel")}
      </Button>
      <Button size="sm" disabled={pending} onClick={onSave}>
        {pending ? t("loading") : t("save_changes")}
      </Button>
    </div>
  );
}

export { SaveRow };

async function uploadIcon(file: File): Promise<{ id: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/eneo/api/v1/icons/", { method: "POST", body: form });
  if (!response.ok) throw new Error(`icon upload failed: ${response.status}`);
  return (await response.json()) as { id: string };
}

function IconField({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const icon = iconUrl(assistant.icon_id);

  async function replaceIcon(file: File) {
    setBusy(true);
    try {
      const uploaded = await uploadIcon(file);
      await update.mutateAsync({ icon_id: uploaded.id });
    } catch {
      toast.error(t("avatar_upload_failed"));
    } finally {
      setBusy(false);
    }
  }

  async function removeIcon() {
    setBusy(true);
    try {
      if (assistant.icon_id) {
        await unwrap(
          browserApi.DELETE("/api/v1/icons/{id}/", {
            params: { path: { id: assistant.icon_id } }
          })
        );
      }
      await update.mutateAsync({ icon_id: null });
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
      {assistant.icon_id && (
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => void removeIcon()}>
          <Trash2 className="size-4" /> {t("delete")}
        </Button>
      )}
    </div>
  );
}

export function GeneralSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const [name, setName] = useState(assistant.name);
  const [description, setDescription] = useState(assistant.description ?? "");

  const dirty = name !== assistant.name || description !== (assistant.description ?? "");

  return (
    <SettingsGroup title={t("general")}>
      <SettingsRow title={t("name")} description={t("assistant_name_description")}>
        <Input value={name} onChange={(event) => setName(event.target.value)} />
      </SettingsRow>
      <SettingsRow title={t("description")} description={t("assistant_description_description")}>
        <Textarea
          value={description}
          rows={4}
          placeholder={t("assistant_placeholder", { name })}
          onChange={(event) => setDescription(event.target.value)}
        />
        <SaveRow
          dirty={dirty}
          pending={update.isPending}
          onSave={() => update.mutate({ name: name.trim(), description })}
          onRevert={() => {
            setName(assistant.name);
            setDescription(assistant.description ?? "");
          }}
        />
      </SettingsRow>
      <SettingsRow title={t("avatar")} description={t("avatar_description")}>
        <IconField assistant={assistant} />
      </SettingsRow>
    </SettingsGroup>
  );
}
