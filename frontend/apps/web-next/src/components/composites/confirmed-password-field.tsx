"use client";

import type * as React from "react";
import { useId } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export function isConfirmedPasswordValid({
  value,
  confirmation,
  required = false
}: {
  value: string;
  confirmation: string;
  required?: boolean;
}) {
  if (value.length === 0 && confirmation.length === 0) return !required;
  return value.length > 0 && value === confirmation;
}

export function ConfirmedPasswordField({
  id,
  label,
  confirmLabel,
  value,
  confirmation,
  onValueChange,
  onConfirmationChange,
  errorMessage,
  description,
  required = false,
  disabled = false,
  autoComplete = "new-password",
  placeholder,
  confirmPlaceholder,
  className
}: {
  id?: string;
  label: string;
  confirmLabel: string;
  value: string;
  confirmation: string;
  onValueChange: (value: string) => void;
  onConfirmationChange: (value: string) => void;
  errorMessage: string;
  description?: string;
  required?: boolean;
  disabled?: boolean;
  autoComplete?: React.ComponentProps<"input">["autoComplete"];
  placeholder?: string;
  confirmPlaceholder?: string;
  className?: string;
}) {
  const generatedId = useId();
  const fieldId = id ?? `confirmed-password-${generatedId}`;
  const confirmationId = `${fieldId}-confirmation`;
  const descriptionId = description ? `${fieldId}-description` : undefined;
  const errorId = `${fieldId}-error`;
  const mismatch = confirmation.length > 0 && value !== confirmation;
  const confirmationRequired = required || value.length > 0;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={fieldId}>
          {label}
          {required && <span aria-hidden="true">*</span>}
        </Label>
        <Input
          id={fieldId}
          type="password"
          autoComplete={autoComplete}
          disabled={disabled}
          required={required}
          value={value}
          placeholder={placeholder}
          aria-invalid={mismatch}
          aria-describedby={descriptionId}
          onChange={(event) => onValueChange(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={confirmationId}>
          {confirmLabel}
          {confirmationRequired && <span aria-hidden="true">*</span>}
        </Label>
        <Input
          id={confirmationId}
          type="password"
          autoComplete={autoComplete}
          disabled={disabled}
          required={confirmationRequired}
          value={confirmation}
          placeholder={confirmPlaceholder}
          aria-invalid={mismatch}
          aria-describedby={mismatch ? errorId : undefined}
          onChange={(event) => onConfirmationChange(event.target.value)}
        />
        {mismatch && (
          <p id={errorId} className="text-destructive text-xs" aria-live="polite">
            {errorMessage}
          </p>
        )}
      </div>
      {description && (
        <p id={descriptionId} className="text-muted-foreground text-xs">
          {description}
        </p>
      )}
    </div>
  );
}
