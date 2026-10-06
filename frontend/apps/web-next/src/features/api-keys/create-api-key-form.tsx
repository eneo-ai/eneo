"use client";

import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { Button } from "@/components/ui/button";
import { DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  API_KEY_EXPIRY_PRESETS,
  type ApiKeyExpiryPresetValue,
  type ApiKeyPermission
} from "./api-keys";

/** What the create form asks for; the caller adds whose key it is. */
export type ApiKeyDraft = {
  name: string;
  permission: ApiKeyPermission;
  expiryDays: ApiKeyExpiryPresetValue;
};

/**
 * The body of a create-key dialog (the account's, the organization's and a
 * resource's): a name, a permission level and an expiry. Mounted while the
 * dialog is open, so each opening starts empty. A missing name shows at the
 * field on submit, which takes focus; the submit button stays enabled, and
 * while `pending` it keeps focus and a second press is ignored.
 */
export function CreateApiKeyForm({
  idPrefix,
  title,
  pending,
  onSubmit,
  onCancel
}: {
  /** Makes the field ids unique on the page. */
  idPrefix: string;
  title: string;
  pending: boolean;
  onSubmit: (draft: ApiKeyDraft) => void;
  onCancel: () => void;
}) {
  const t = useTranslations();
  const [name, setName] = useState("");
  const [permission, setPermission] = useState<ApiKeyPermission>("read");
  const [expiryDays, setExpiryDays] = useState<ApiKeyExpiryPresetValue>("30");
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const nameProblem = name.trim() ? null : t("required_field");
  const shownNameProblem = submitted ? nameProblem : null;
  const id = (field: string) => `${idPrefix}-key-${field}`;

  return (
    <form
      className="flex flex-col gap-4"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (pending) return;
        if (nameProblem) {
          // Rendered before focus moves, so the field is read with its error.
          flushSync(() => setSubmitted(true));
          nameRef.current?.focus();
          return;
        }
        onSubmit({ name, permission, expiryDays });
      }}
    >
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
      </DialogHeader>
      <div className="flex flex-col gap-2">
        <Label htmlFor={id("name")}>{t("name")}</Label>
        <Input
          ref={nameRef}
          id={id("name")}
          value={name}
          placeholder={t("api_keys_name_placeholder")}
          onChange={(event) => setName(event.target.value)}
          required
          {...fieldProblemProps(id("name"), shownNameProblem)}
        />
        <FieldProblem id={id("name")} problem={shownNameProblem} />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={id("permission")}>{t("api_keys_permission_level")}</Label>
        <Select
          value={permission}
          onValueChange={(next) => setPermission(next as ApiKeyPermission)}
        >
          <SelectTrigger id={id("permission")} className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="read">{t("api_keys_permission_read")}</SelectItem>
            <SelectItem value="write">{t("api_keys_permission_write")}</SelectItem>
            <SelectItem value="admin">{t("api_keys_permission_admin")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={id("expiry")}>{t("api_keys_expiration")}</Label>
        <Select
          value={expiryDays}
          onValueChange={(value) => setExpiryDays(value as ApiKeyExpiryPresetValue)}
        >
          <SelectTrigger id={id("expiry")} className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {API_KEY_EXPIRY_PRESETS.map((preset) => (
              <SelectItem key={preset.key} value={preset.value}>
                {t(preset.key)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t("cancel")}
        </Button>
        <Button type="submit" aria-busy={pending || undefined}>
          {pending ? t("api_keys_creating") : t("api_keys_create_short")}
        </Button>
      </DialogFooter>
    </form>
  );
}
