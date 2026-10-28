"use client";

import { Edit, FileAudio, FileImage, FileText, Mic } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import type { InputFieldType } from "../apps";

/** Each input type's icon and name (the Svelte InputTypeSelect's list). */
export const INPUT_TYPE_META: Record<InputFieldType, { icon: typeof Edit; labelKey: string }> = {
  "text-field": { icon: Edit, labelKey: "enter_text_directly" },
  "text-upload": { icon: FileText, labelKey: "upload_text_document" },
  "audio-recorder": { icon: Mic, labelKey: "record_microphone_audio" },
  "audio-upload": { icon: FileAudio, labelKey: "upload_audio_file" },
  "image-upload": { icon: FileImage, labelKey: "upload_image_file" }
};

const TYPE_GROUPS: { labelKey: string; types: InputFieldType[] }[] = [
  { labelKey: "text", types: ["text-field", "text-upload"] },
  { labelKey: "audio", types: ["audio-recorder", "audio-upload"] },
  { labelKey: "image", types: ["image-upload"] }
];

/** Whether `value` is one of the input types the backend accepts. */
export function isInputFieldType(value: string | null | undefined): value is InputFieldType {
  return value != null && Object.hasOwn(INPUT_TYPE_META, value);
}

/**
 * The input type picker, grouped by text, audio and image. `null` (a stored
 * value that is not a known type) shows "Inget valt" until one is chosen.
 */
export function InputTypeSelect({
  id,
  value,
  onChange,
  ...aria
}: {
  id: string;
  value: InputFieldType | null;
  onChange: (value: InputFieldType) => void;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}) {
  const t = useTranslations();
  const Icon = value ? INPUT_TYPE_META[value].icon : null;
  return (
    <Select value={value ?? ""} onValueChange={(next) => onChange(next as InputFieldType)}>
      <SelectTrigger id={id} className="w-full" {...aria}>
        <SelectValue placeholder={t("nothing_selected")}>
          {value && Icon ? (
            <span className="flex items-center gap-2">
              <Icon className="size-4" />
              {t(INPUT_TYPE_META[value].labelKey)}
            </span>
          ) : undefined}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {TYPE_GROUPS.map(({ labelKey, types }) => (
          <SelectGroup key={labelKey}>
            <SelectLabel>{t(labelKey)}</SelectLabel>
            {types.map((type) => {
              const TypeIcon = INPUT_TYPE_META[type].icon;
              return (
                <SelectItem key={type} value={type}>
                  <span className="flex items-center gap-2">
                    <TypeIcon className="size-4" />
                    {t(INPUT_TYPE_META[type].labelKey)}
                  </span>
                </SelectItem>
              );
            })}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
}
