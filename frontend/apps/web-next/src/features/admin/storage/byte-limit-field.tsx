"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { isValidByteLimit, UNIT_BYTES, unitForBytes } from "./storage-policy";

type Unit = keyof typeof UNIT_BYTES;
const units: Unit[] = ["B", "KB", "MB", "GB"];

export function ByteLimitField({
  id,
  label,
  description,
  bytes,
  storedBytes,
  disabled,
  onChange
}: {
  id: string;
  label: string;
  description: string;
  bytes: number;
  storedBytes: number;
  disabled: boolean;
  onChange: (bytes: number) => void;
}) {
  const t = useTranslations();
  const [unit, setUnit] = useState<Unit>(() => unitForBytes(storedBytes));
  const valid = isValidByteLimit(bytes);

  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="grid grid-cols-[minmax(0,1fr)_6.5rem] gap-2">
        <Input
          id={id}
          type="number"
          min="0"
          step="any"
          required
          disabled={disabled}
          aria-invalid={!valid}
          aria-describedby={`${id}-description`}
          value={Number.isNaN(bytes) ? "" : bytes / UNIT_BYTES[unit]}
          onChange={(event) =>
            onChange(
              event.target.value === "" ? Number.NaN : Number(event.target.value) * UNIT_BYTES[unit]
            )
          }
        />
        <select
          value={unit}
          onChange={(event) => setUnit(event.target.value as Unit)}
          disabled={disabled}
          aria-label={t("storage_limit_unit", { limit: label })}
          aria-describedby={`${id}-description`}
          aria-invalid={!valid}
          className="bg-background border-input focus-visible:ring-ring h-9 rounded-md border px-2 text-sm focus-visible:ring-2 focus-visible:outline-none"
        >
          {units.map((candidate) => (
            <option key={candidate} value={candidate}>
              {candidate}
            </option>
          ))}
        </select>
      </div>
      <p id={`${id}-description`} className="text-muted-foreground text-sm">
        {description}
      </p>
    </div>
  );
}
