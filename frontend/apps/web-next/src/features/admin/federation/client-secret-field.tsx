"use client";

import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useRef } from "react";
import { flushSync } from "react-dom";
import { QuietBanner } from "@/components/astryx/banner";
import { TextInput } from "@/components/astryx/text-input";
import type { FederationView } from "./federation";

/**
 * The client secret is write-only: the page says when it was saved and offers
 * "Byt hemlighet", which opens an empty password field (never prefilled). The
 * typed value lives only in the form's draft, which a save or "Behåll" clears.
 */
export function ClientSecretField({
  view,
  secret,
  onSecretChange,
  problem,
  inputRef
}: {
  view: FederationView;
  /** null while the stored secret is kept. */
  secret: string | null;
  onSecretChange: (secret: string | null) => void;
  problem: string | null;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const labelId = useId();
  const replaceRef = useRef<HTMLButtonElement>(null);

  if (secret !== null) {
    return (
      <div className="flex flex-col gap-2">
        <TextInput
          ref={inputRef}
          type="password"
          label={t("client_secret")}
          description={t("federation_admin_secret_help")}
          value={secret}
          onChange={onSecretChange}
          autoComplete="new-password"
          isRequired
          status={problem ? { type: "error", message: problem } : undefined}
        />
        <Button
          size="sm"
          label={t("federation_admin_secret_keep")}
          className="self-start"
          onClick={() => {
            flushSync(() => onSecretChange(null));
            replaceRef.current?.focus();
          }}
        />
      </div>
    );
  }

  const savedAt = view.client_secret_updated_at
    ? format.dateTime(new Date(view.client_secret_updated_at), {
        dateStyle: "medium",
        timeStyle: "short"
      })
    : "—";
  return (
    <div role="group" aria-labelledby={labelId} className="flex flex-col gap-2">
      <Text id={labelId} weight="semibold">
        {t("client_secret")}
      </Text>
      <Text type="supporting">{t("federation_admin_secret_saved", { date: savedAt })}</Text>
      {view.encryption_status === "plaintext" ? (
        <QuietBanner status="warning" title={t("federation_admin_secret_plaintext")} />
      ) : null}
      <Button
        ref={replaceRef}
        size="sm"
        label={t("federation_admin_secret_replace")}
        className="self-start"
        onClick={() => {
          flushSync(() => onSecretChange(""));
          inputRef.current?.focus();
        }}
      />
    </div>
  );
}
