"use client";

import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Switch } from "@/components/astryx/switch";
import { TextInput } from "@/components/astryx/text-input";
import { IconField, iconUrl, uploadIcon } from "@/components/composites/icon-field";
import type { Schema } from "@/lib/api/models";
import { WidgetPersonaByline } from "../components/widget-persona-byline";
import { monogram } from "../persona";
import { collapseWhitespace } from "./text";
import { DraftWrapper, useTextDraft } from "./use-text-draft";

type WidgetPersona = Schema<"WidgetPersona">;

/**
 * The persona a widget or template answers with: a name, an uploaded avatar
 * and whether that avatar is the launcher button on the host page. Shared by
 * the widget editor and the template page; the caller saves the change.
 *
 * The avatar id is public and only the editor's own uploads are accepted by
 * the API, so "use the assistant's icon" copies the image into a new upload
 * instead of sharing the id. Removing an avatar only clears the reference:
 * the server deletes the image once nothing shows it.
 */
export function WidgetPersonaFields({
  persona,
  chatTitle = "",
  assistantIconId = null,
  locked = false,
  lockHint = "",
  errors = {},
  onChange
}: {
  persona: WidgetPersona;
  /** The chat's title, to warn when the persona repeats it. */
  chatTitle?: string;
  /** The assistant behind the widget, whose icon can be copied. */
  assistantIconId?: string | null;
  locked?: boolean;
  lockHint?: string;
  errors?: Record<string, string>;
  onChange: (persona: WidgetPersona) => void;
}) {
  const t = useTranslations();
  // The name is typed; the API echoes it cleaned, so the draft keeps the
  // editor's spacing while they type.
  const name = useTextDraft(persona.name ?? "");
  // A monogram is the first character, so it must be a letter; the API
  // refuses anything else, and the field says so before a save is tried.
  const nameInvalid = !!collapseWhitespace(name.text) && !/^\p{L}/u.test(name.text.trim());
  const nameProblem = nameInvalid ? t("widget_admin_persona_name_invalid") : errors["name"];
  const repeatsTitle =
    !!collapseWhitespace(name.text) &&
    collapseWhitespace(name.text).toLocaleLowerCase() ===
      collapseWhitespace(chatTitle).toLocaleLowerCase();
  const savedName = persona.name ?? "";
  const hasName = savedName.length > 0;
  const avatarUrl = iconUrl(persona.avatar_icon_id);

  function setName(value: string) {
    const next = value.slice(0, 30);
    name.setText(next);
    if (!!collapseWhitespace(next) && !/^\p{L}/u.test(next.trim())) return;
    const cleaned = collapseWhitespace(next);
    if (cleaned === persona.name) return;
    // No name, no face: the API refuses an avatar on an empty persona.
    onChange(
      cleaned
        ? { ...persona, name: cleaned }
        : { ...persona, name: "", avatar_icon_id: null, avatar_in_launcher: false }
    );
  }

  const [copying, setCopying] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  async function copyAssistantIcon() {
    if (!assistantIconId || copying) return;
    setCopying(true);
    setCopyFailed(false);
    try {
      const response = await fetch(iconUrl(assistantIconId) ?? "");
      if (!response.ok) throw new Error(`Icon fetch returned ${response.status}`);
      const blob = await response.blob();
      const uploaded = await uploadIcon(new File([blob], "avatar", { type: blob.type }));
      onChange({ ...persona, avatar_icon_id: uploaded.id });
    } catch (error) {
      console.error("Failed to copy the assistant's icon:", error);
      setCopyFailed(true);
    } finally {
      setCopying(false);
    }
  }

  const preview = hasName
    ? {
        name: savedName,
        avatarUrl,
        monogram: monogram(savedName),
        inLauncher: persona.avatar_in_launcher ?? false
      }
    : null;

  return (
    <div className="flex flex-col gap-6">
      {locked && <p className="text-ax-text-secondary text-sm">{lockHint}</p>}

      <DraftWrapper onFocus={name.onFocus} onBlur={name.onBlur}>
        <TextInput
          label={t("widget_admin_persona_name")}
          description={t("widget_admin_persona_name_description")}
          value={name.text}
          onChange={setName}
          isDisabled={locked}
          disabledMessage={locked ? lockHint : undefined}
          status={
            nameProblem
              ? { type: "error", message: nameProblem }
              : repeatsTitle
                ? { type: "warning", message: t("widget_admin_persona_name_same_as_title") }
                : undefined
          }
          width="100%"
        />
      </DraftWrapper>

      <div className="flex flex-col gap-2" role="group" aria-labelledby="widget-persona-avatar">
        <p id="widget-persona-avatar" className="text-sm font-medium">
          {t("widget_admin_persona_avatar")}
        </p>
        <p className="text-ax-text-secondary text-sm">
          {t("widget_admin_persona_avatar_description")}
        </p>
        {!hasName ? (
          <p className="text-ax-text-secondary text-sm">
            {t("widget_admin_persona_avatar_needs_name")}
          </p>
        ) : locked ? (
          avatarUrl && (
            // The upload behind this app's icon proxy; next/image has nothing to add.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              className="size-16 rounded-full object-cover"
              src={avatarUrl}
              alt=""
              width={64}
              height={64}
            />
          )
        ) : (
          <div className="flex flex-col gap-2">
            <IconField
              iconId={persona.avatar_icon_id}
              onSave={async (iconId) =>
                onChange(
                  iconId
                    ? { ...persona, avatar_icon_id: iconId }
                    : { ...persona, avatar_icon_id: null, avatar_in_launcher: false }
                )
              }
            />
            {assistantIconId && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  label={t("widget_admin_persona_use_assistant_icon")}
                  isLoading={copying}
                  isInterruptible
                  clickAction={copyAssistantIcon}
                />
                <span className="text-ax-text-secondary text-xs">
                  {t("widget_admin_persona_use_assistant_icon_description")}
                </span>
              </div>
            )}
            {copyFailed && (
              <p role="alert" className="text-ax-red text-sm">
                {t("widget_admin_persona_use_assistant_icon_failed")}
              </p>
            )}
            {errors["avatar_icon_id"] && (
              <p className="text-ax-red text-sm">{errors["avatar_icon_id"]}</p>
            )}
          </div>
        )}
      </div>

      {persona.avatar_icon_id && (
        <Switch
          label={t("widget_admin_persona_in_launcher")}
          description={t("widget_admin_persona_in_launcher_description")}
          value={persona.avatar_in_launcher ?? false}
          isDisabled={locked}
          disabledMessage={locked ? lockHint : undefined}
          labelPosition="start"
          labelSpacing="spread"
          width="100%"
          onChange={(checked) => onChange({ ...persona, avatar_in_launcher: checked })}
        />
      )}

      {preview && (
        <div className="border-ax-border flex flex-col gap-3 rounded-lg border p-4">
          <p className="text-ax-text-secondary text-xs">{t("widget_admin_persona_preview")}</p>
          <WidgetPersonaByline persona={preview} />
        </div>
      )}
    </div>
  );
}
