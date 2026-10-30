// Copyright (c) 2026 Sundsvalls Kommun
"use client";

import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useId, useRef } from "react";
import { flushSync } from "react-dom";
import { useTranslations } from "use-intl";
import { Plus, Trash2 } from "lucide-react";
import { QuietBanner } from "@/components/astryx/banner";
import { Switch } from "@/components/astryx/switch";
import { TextInput } from "@/components/astryx/text-input";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { LoadingState } from "@/components/composites/loading-state";
import type { useFieldFocus } from "./provider-form-fields";
import {
  canKeepStored,
  changeStored,
  headerClassification,
  insertToken,
  isUnencryptedRemote,
  keepStored,
  newHeaderRow,
  setSecret,
  supportsOutboundHeaders,
  tokenProblems,
  type HeaderRow,
  type OutboundHeaderOptions,
  type StoredPart
} from "./outbound-headers";

export function OutboundHeadersEditor({
  providerType,
  options,
  optionsError,
  loading,
  onRetry,
  rows,
  onChange,
  focus,
  endpoint,
  editing = false,
  showErrors = false,
  endpointProblem
}: {
  providerType: string;
  options: OutboundHeaderOptions | null;
  optionsError: boolean;
  loading: boolean;
  onRetry: () => void;
  rows: HeaderRow[];
  onChange: (rows: HeaderRow[]) => void;
  focus: ReturnType<typeof useFieldFocus>;
  endpoint?: string;
  editing?: boolean;
  showErrors?: boolean;
  endpointProblem?: string;
}) {
  const t = useTranslations();
  const id = useId();
  const addRef = useRef<HTMLButtonElement>(null);
  const classification = headerClassification(rows, options);
  if (options && !supportsOutboundHeaders(options, providerType)) return null;

  function update(row: HeaderRow) {
    onChange(rows.map((current) => (current.key === row.key ? row : current)));
  }
  function remove(index: number) {
    const next = rows[index + 1] ?? rows[index - 1];
    flushSync(() => onChange(rows.filter((_, i) => i !== index)));
    if (next) focus.focus(`${next.key}:name`);
    else addRef.current?.focus();
  }
  function storedPart(row: HeaderRow, part: StoredPart, label: string) {
    const keeping = part === "value" ? row.keepsStoredValue : row.keepsStoredFallback;
    const inputLabel = t(part === "value" ? "outbound_headers_value" : "outbound_headers_fallback");
    const problems = part === "value" && !keeping ? tokenProblems(row.value, options) : null;
    const message = problems
      ? problems.unknown.length
        ? t("outbound_headers_unknown_token", {
            tokens: problems.unknown.map((token) => `{{${token}}}`).join(", ")
          })
        : t("outbound_headers_malformed_token", {
            example: `{{${options?.dynamic_values[0]?.token ?? "user.department"}}}`
          })
      : showErrors && !row[part]
        ? t("provider_form_field_required")
        : undefined;
    const changeId = `${id}-${row.key}-${part}-change`;
    return (
      <div className="flex min-w-0 flex-col gap-2">
        {keeping ? (
          <div
            role="group"
            aria-label={inputLabel}
            className="flex flex-wrap items-center justify-between gap-2"
          >
            <Text type="label">{inputLabel}</Text>
            <Button
              id={changeId}
              size="sm"
              label={t(
                part === "value"
                  ? "outbound_headers_change_value"
                  : "outbound_headers_change_fallback",
                { name: label }
              )}
              onClick={() => {
                flushSync(() => update(changeStored(row, part)));
                focus.focus(`${row.key}:${part}`);
              }}
            />
          </div>
        ) : (
          <>
            <TextInput
              ref={focus.ref(`${row.key}:${part}`)}
              label={inputLabel}
              type={row.secret ? "password" : "text"}
              autoComplete="off"
              isRequired
              value={row[part]}
              onChange={(value) => update({ ...row, [part]: value })}
              description={t(
                part === "value" ? "outbound_headers_value_hint" : "outbound_headers_fallback_hint"
              )}
              status={message ? { type: "error", message } : undefined}
            />
            {part === "value" && options && options.dynamic_values.length > 0 && (
              <DropdownMenu
                presentation="adaptive"
                button={{
                  label: t("outbound_headers_insert_dynamic_value"),
                  size: "sm",
                  variant: "ghost"
                }}
                items={options.dynamic_values.map((value) => ({
                  id: value.token,
                  label: `{{${value.token}}}`,
                  description: [
                    value.source === "external_id"
                      ? t("outbound_headers_token_source_external_id")
                      : t("outbound_headers_token_source_scim", { attribute: value.attribute }),
                    value.classification === "identifying"
                      ? t("outbound_headers_token_identifying")
                      : null
                  ]
                    .filter(Boolean)
                    .join(" · "),
                  onClick: () => update({ ...row, value: insertToken(row.value, value.token) })
                }))}
              />
            )}
            {canKeepStored(row, part) && (
              <Button
                size="sm"
                variant="ghost"
                className="self-start"
                label={t(
                  part === "value"
                    ? "outbound_headers_keep_value"
                    : "outbound_headers_keep_fallback"
                )}
                onClick={() => {
                  flushSync(() => update(keepStored(row, part)));
                  document.getElementById(changeId)?.focus();
                }}
              />
            )}
            {row.wasSecret && !row.secret && (
              <Text type="supporting">
                {t(
                  part === "value"
                    ? "outbound_headers_secret_reenter"
                    : "outbound_headers_secret_reenter_fallback"
                )}
              </Text>
            )}
          </>
        )}
      </div>
    );
  }

  const problem = endpointProblem ?? null;
  return (
    <fieldset className="flex min-w-0 flex-col gap-4" {...fieldProblemProps(id, problem)}>
      <legend className="text-ax-text mb-3 text-sm font-semibold">
        {t("outbound_headers_title")}
      </legend>
      <FieldProblem id={id} problem={problem} />
      {!options ? (
        optionsError ? (
          <QuietBanner
            status="warning"
            title={t("outbound_headers_options_failed")}
            collapsible={false}
          >
            <div className="flex flex-col items-start gap-2">
              <Text>
                {t(
                  editing
                    ? "outbound_headers_options_failed_kept"
                    : "outbound_headers_options_failed_create"
                )}
              </Text>
              <Button label={t("retry")} onClick={onRetry} isLoading={loading} isInterruptible />
            </div>
          </QuietBanner>
        ) : (
          <LoadingState rows={1} />
        )
      ) : (
        <>
          <Text type="supporting">{t("outbound_headers_description")}</Text>
          {rows.map((row, index) => {
            const label = row.name.trim() || t("outbound_headers_unnamed", { position: index + 1 });
            return (
              <fieldset
                key={row.key}
                className="border-ax-border flex min-w-0 flex-col gap-4 border-t pt-4"
              >
                <legend className="sr-only">{label}</legend>
                <div className="flex items-end gap-2">
                  <TextInput
                    ref={focus.ref(`${row.key}:name`)}
                    label={t("outbound_headers_name")}
                    value={row.name}
                    onChange={(name) => update({ ...row, name })}
                    autoComplete="off"
                    isRequired
                    className="min-w-0 flex-1"
                    placeholder={t("outbound_headers_name_placeholder")}
                    status={
                      showErrors && !row.name.trim()
                        ? { type: "error", message: t("provider_form_field_required") }
                        : undefined
                    }
                  />
                  <Button
                    label={t("outbound_headers_remove_named", { name: label })}
                    isIconOnly
                    icon={<Trash2 />}
                    variant="ghost"
                    onClick={() => remove(index)}
                  />
                </div>
                {storedPart(row, "value", label)}
                <Selector
                  label={t("outbound_headers_encoding")}
                  value={row.encoding}
                  description={t(
                    row.encoding === "none"
                      ? "outbound_headers_encoding_none_hint"
                      : "outbound_headers_encoding_percent_hint"
                  )}
                  options={[
                    { value: "percent", label: t("outbound_headers_encoding_percent") },
                    { value: "none", label: t("outbound_headers_encoding_none") }
                  ]}
                  onChange={(value) =>
                    update({ ...row, encoding: value === "none" ? "none" : "percent" })
                  }
                />
                <Selector
                  label={t("outbound_headers_on_missing")}
                  value={row.onMissing}
                  options={[
                    { value: "omit", label: t("outbound_headers_on_missing_omit") },
                    { value: "fallback", label: t("outbound_headers_on_missing_fallback") },
                    { value: "fail", label: t("outbound_headers_on_missing_fail") }
                  ]}
                  onChange={(value) =>
                    update({
                      ...row,
                      onMissing: value === "fallback" || value === "fail" ? value : "omit"
                    })
                  }
                />
                {row.onMissing === "fallback" && storedPart(row, "fallback", label)}
                {row.onMissing === "fail" && (
                  <QuietBanner status="warning" title={t("outbound_headers_fail_warning")} />
                )}
                <Switch
                  label={t("outbound_headers_secret")}
                  description={t("outbound_headers_secret_hint")}
                  value={row.secret}
                  onChange={(secret) => update(setSecret(row, secret))}
                />
              </fieldset>
            );
          })}
          <Button
            ref={addRef}
            label={t("outbound_headers_add")}
            icon={<Plus />}
            className="self-start"
            isDisabled={rows.length >= options.max_headers}
            onClick={() => {
              const row = newHeaderRow();
              flushSync(() => onChange([...rows, row]));
              focus.focus(`${row.key}:name`);
            }}
          />
          {rows.length >= options.max_headers && (
            <Text type="supporting">
              {t("outbound_headers_max_reached", { max: options.max_headers })}
            </Text>
          )}
          {classification && (
            <QuietBanner
              status="info"
              title={t(
                classification === "identifying"
                  ? "outbound_headers_notice_identifying"
                  : "outbound_headers_notice_organisational"
              )}
            />
          )}
          {(classification || rows.some((row) => row.secret)) && isUnencryptedRemote(endpoint) && (
            <QuietBanner status="warning" title={t("outbound_headers_plain_http_warning")} />
          )}
          {rows.length > 0 && (
            <Text type="supporting">{t("outbound_headers_blocked_operations_note")}</Text>
          )}
        </>
      )}
    </fieldset>
  );
}
