// Copyright (c) 2026 Sundsvalls Kommun
"use client";

import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useTranslations } from "use-intl";
import { QuietBanner } from "@/components/astryx/banner";
import { TextInput } from "@/components/astryx/text-input";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { adminUsersQueryOptions, MIN_SEARCH_LENGTH } from "../users/users";
import { previewOutboundHeaders } from "./model-providers";

type PreviewUser = { id: string; email: string };

function PreviewForUser({ providerId, user }: { providerId: string; user: PreviewUser }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const preview = useMutation({
    mutationFn: () => previewOutboundHeaders(browserApi, providerId, user.id)
  });
  const result = preview.data;
  const resultLabel = result?.blocked
    ? t("outbound_headers_preview_blocked")
    : t("outbound_headers_preview_sent");
  function run() {
    if (preview.isPending) return;
    preview.mutate(undefined, {
      onSuccess: (data) =>
        announce(
          data.blocked ? t("outbound_headers_preview_blocked") : t("outbound_headers_preview_sent")
        )
    });
  }
  const reason = (code: string | null | undefined) => {
    switch (code) {
      case "control_character":
        return t("outbound_headers_reason_control_character");
      case "non_ascii":
        return t("outbound_headers_reason_non_ascii");
      case "value_too_long":
        return t("outbound_headers_reason_value_too_long");
      case "total_size_exceeded":
        return t("outbound_headers_reason_total_size");
      case "decryption_failed":
        return t("outbound_headers_reason_decryption_failed");
      default:
        return null;
    }
  };
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <Button
        className="self-start"
        label={t("outbound_headers_preview_run")}
        onClick={run}
        isLoading={preview.isPending}
        isInterruptible
      />
      {preview.isError && (
        <ListError error={preview.error} title={t("outbound_headers_preview_title")} />
      )}
      {result && (
        <>
          <QuietBanner
            status={result.blocked ? "warning" : "success"}
            title={resultLabel}
            description={
              [
                result.destination_problem ? t("outbound_headers_destination_problem") : null,
                reason(result.blocked_reason)
              ]
                .filter(Boolean)
                .join(" ") || undefined
            }
          />
          <ul className="border-ax-border divide-ax-border rounded-ax-container divide-y border">
            {result.headers.map((header) => (
              <li key={header.name} className="flex min-w-0 flex-col gap-1 p-3">
                <Text type="label" className="break-all">
                  {header.name}
                </Text>
                <Text>
                  {header.state === "resolved"
                    ? t("outbound_headers_preview_state_resolved")
                    : header.state === "missing"
                      ? t("outbound_headers_preview_state_missing")
                      : t("outbound_headers_preview_state_invalid")}
                </Text>
                {header.policy && (
                  <Text type="supporting">
                    {header.policy === "omit"
                      ? t("outbound_headers_on_missing_omit")
                      : header.policy === "fallback"
                        ? t("outbound_headers_on_missing_fallback")
                        : t("outbound_headers_on_missing_fail")}
                  </Text>
                )}
                {header.secret ? (
                  <Text type="supporting">{t("outbound_headers_preview_secret_hidden")}</Text>
                ) : (
                  header.value && (
                    <Text type="code" className="break-all">
                      {header.value}
                    </Text>
                  )
                )}
                {reason(header.reason) && <Text>{reason(header.reason)}</Text>}
                {!!header.missing_dynamic_values?.length && (
                  <Text type="supporting">
                    {t("outbound_headers_preview_missing_values", {
                      tokens: header.missing_dynamic_values.join(", ")
                    })}
                  </Text>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function SavedHeadersPreview({ providerId }: { providerId: string }) {
  const t = useTranslations();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<PreviewUser | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const debounced = useDebouncedValue(search.trim());
  const users = useQuery({
    ...adminUsersQueryOptions(browserApi, { page: 1, pageSize: 8, search: debounced }),
    enabled: selected === null && debounced.length >= MIN_SEARCH_LENGTH
  });
  const searchIsCurrent = debounced === search.trim() && debounced.length >= MIN_SEARCH_LENGTH;
  const previewPanel = useRef<HTMLDivElement>(null);
  return (
    <>
      {selected ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Text className="break-all">{selected.email}</Text>
          <Button
            label={t("change")}
            onClick={() => {
              flushSync(() => {
                setSelected(null);
                setSearch("");
              });
              input.current?.focus();
            }}
          />
        </div>
      ) : (
        <>
          <TextInput
            ref={input}
            label={t("outbound_headers_preview_search")}
            value={search}
            onChange={setSearch}
            description={t("audit_user_search_hint", { count: MIN_SEARCH_LENGTH })}
            autoComplete="off"
          />
          {searchIsCurrent && (
            <QueryStateBoundary query={users}>
              {() => (
                <>
                  {users.data?.items.length === 0 && (
                    <Text type="supporting">{t("outbound_headers_preview_no_users")}</Text>
                  )}
                  <ul className="flex flex-col gap-1">
                    {users.data?.items.map((user) => (
                      <li key={user.id}>
                        <Button
                          label={user.email}
                          variant="ghost"
                          onClick={() => {
                            flushSync(() => setSelected({ id: user.id, email: user.email }));
                            previewPanel.current
                              ?.querySelector<HTMLButtonElement>("button")
                              ?.focus();
                          }}
                        />
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </QueryStateBoundary>
          )}
        </>
      )}
      <div ref={previewPanel}>
        {selected && <PreviewForUser key={selected.id} providerId={providerId} user={selected} />}
      </div>
    </>
  );
}

export function OutboundHeadersPreview({
  providerId,
  hasUnsavedChanges
}: {
  providerId: string;
  hasUnsavedChanges: boolean;
}) {
  const t = useTranslations();
  return (
    <fieldset className="border-ax-border flex min-w-0 flex-col gap-3 border-t pt-4">
      <legend className="text-ax-text text-sm font-semibold">
        {t("outbound_headers_preview_title")}
      </legend>
      <Text type="supporting">{t("outbound_headers_preview_description")}</Text>
      {hasUnsavedChanges ? (
        <Text type="supporting">{t("outbound_headers_preview_unsaved")}</Text>
      ) : (
        <SavedHeadersPreview key={providerId} providerId={providerId} />
      )}
    </fieldset>
  );
}
