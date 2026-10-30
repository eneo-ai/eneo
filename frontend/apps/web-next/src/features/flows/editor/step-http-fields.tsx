"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Token } from "@astryxdesign/core/Token";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, KeyRound, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useState } from "react";
import { TextInput } from "@astryxdesign/core/TextInput";
import { isJsonObject } from "./step-types";
import { testHttp, type HttpTestResponse } from "./editor-api";
import { FieldMessage, problemStatus, VariablePicker } from "./editor-fields";
import { TemplateTextArea } from "./reference-text-area";
import { describeSaveError } from "./field-problems";
import {
  httpUrlProblem,
  isSecretSentinel,
  type HttpBodyMode,
  type HttpConfig,
  type HttpHeader,
  type SecretValue
} from "./step-configs";
import { insertToken, type VariableGroup } from "./step-variables";

/**
 * A credential is write-only. A stored one is shown as "Sparad" with Replace;
 * a typed one is a password field that never shows what is stored. Keeping
 * the stored one sends its sentinel back, which the core reads as "unchanged".
 */
function SecretField({
  label,
  value,
  onChange,
  status
}: {
  label: string;
  value: SecretValue;
  onChange: (value: SecretValue) => void;
  status?: { type: "error"; message?: string };
}) {
  const t = useTranslations();
  const [replacing, setReplacing] = useState(false);
  const stored = isSecretSentinel(value);
  if (stored && !replacing) {
    return (
      <div className="flex flex-col gap-1">
        <Text type="label" as="p" display="block" className="m-0">
          {label}
        </Text>
        <div className="flex flex-wrap items-center gap-2">
          <Token
            label={t("flow_step_editor_secret_stored")}
            icon={<KeyRound className="size-3.5" aria-hidden="true" />}
            color="green"
          />
          <Button
            label={t("flow_step_editor_secret_replace", { field: label })}
            variant="secondary"
            size="sm"
            onClick={() => {
              setReplacing(true);
              onChange("");
            }}
          />
        </div>
        <FieldMessage message={status?.message} />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <TextInput
        label={label}
        type="password"
        autoComplete="new-password"
        value={typeof value === "string" ? value : ""}
        onChange={onChange}
        isRequired
        status={status}
      />
      {replacing && (
        <div>
          <Button
            label={t("flow_step_editor_secret_keep")}
            variant="ghost"
            size="sm"
            onClick={() => {
              setReplacing(false);
              onChange({ $secret: "stored" });
            }}
          />
        </div>
      )}
    </div>
  );
}

function HeaderRow({
  header,
  index,
  onChange,
  onRemove
}: {
  header: HttpHeader;
  index: number;
  onChange: (header: HttpHeader) => void;
  onRemove: () => void;
}) {
  const t = useTranslations();
  return (
    <li className="border-ax-border rounded-ax-element flex flex-col gap-3 border p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <TextInput
          label={t("flow_step_editor_http_header_name", { index: index + 1 })}
          value={header.name}
          onChange={(name) => onChange({ ...header, name })}
          autoComplete="off"
        />
        {header.secret ? (
          <SecretField
            label={t("flow_step_editor_http_header_value", { index: index + 1 })}
            value={header.value}
            onChange={(value) => onChange({ ...header, value })}
          />
        ) : (
          <TextInput
            label={t("flow_step_editor_http_header_value", { index: index + 1 })}
            value={typeof header.value === "string" ? header.value : ""}
            onChange={(value) => onChange({ ...header, value })}
            autoComplete="off"
          />
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CheckboxInput
          label={t("flow_step_editor_http_header_secret", { index: index + 1 })}
          value={header.secret}
          // Turning a stored secret into plain text would show nothing of it:
          // it starts empty, as a new value.
          onChange={(secret) =>
            onChange({
              ...header,
              secret,
              value: isSecretSentinel(header.value) ? "" : header.value
            })
          }
        />
        <Button
          label={t("flow_step_editor_http_header_remove", { index: index + 1 })}
          variant="ghost"
          size="sm"
          icon={<Trash2 className="size-4" aria-hidden="true" />}
          onClick={onRemove}
        />
      </div>
    </li>
  );
}

const TEST_ERROR_KEYS: Record<NonNullable<HttpTestResponse["error_code"]>, string> = {
  HTTP_MISSING_URL: "http_test_needs_url",
  HTTP_INVALID_URL: "flow_step_editor_http_url_invalid",
  HTTP_VARIABLE_RESOLUTION_FAILED: "http_test_variable_resolution_failed",
  HTTP_UNRESOLVED_STORED_SECRET: "http_test_saved_secret_unavailable",
  HTTP_MISSING_AUTH: "http_test_auth_missing",
  HTTP_INVALID_BODY_JSON: "http_test_body_invalid",
  HTTP_BODY_NOT_ALLOWED_FOR_GET: "http_test_body_not_allowed",
  HTTP_TIMEOUT_OUT_OF_RANGE: "http_test_timeout_invalid",
  HTTP_TIMEOUT: "flow_error_typed_io_http_timeout",
  HTTP_CONNECTION_REFUSED: "flow_error_typed_io_http_connection_error",
  HTTP_BLOCKED_URL: "flow_error_typed_io_http_ssrf_blocked",
  HTTP_RESPONSE_TOO_LARGE: "flow_error_typed_io_http_response_too_large",
  HTTP_STATUS_ERROR: "flow_error_typed_io_http_non_success",
  HTTP_CREDENTIALS_REQUIRE_HTTPS: "http_test_credentials_require_https"
};

type TestOutcome = { ok: boolean; message: string; preview: string | null };

/**
 * One test request with the step's settings as they stand in the form. The
 * core resolves a stored credential from the saved step, so a step that has
 * never been saved cannot be tested. A URL or body with variables is filled
 * from test values that are only used for the test.
 */
function HttpTest({
  flowId,
  stepId,
  direction,
  config
}: {
  flowId: string;
  stepId: string;
  direction: "input" | "output";
  config: HttpConfig;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const previewId = useId();
  const [variables, setVariables] = useState("{}");
  const [variablesProblem, setVariablesProblem] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<TestOutcome | null>(null);
  const templated = JSON.stringify(config).includes("{{");

  function report(next: TestOutcome) {
    setOutcome(next);
    announce(next.message);
  }

  const test = useMutation({
    mutationFn: (testVariables: Record<string, unknown>) =>
      testHttp(flowId, {
        step_id: stepId,
        config,
        direction,
        method: direction === "input" ? "GET" : "POST",
        test_variables: testVariables
      }),
    onSuccess: (result) =>
      report(
        result.success
          ? {
              ok: true,
              message: result.status_code
                ? `${t("http_test_success")} (${result.status_code})`
                : t("http_test_success"),
              preview: result.response_preview ?? null
            }
          : {
              ok: false,
              message: `${t("http_test_failed_prefix")}: ${
                result.error_code
                  ? t(TEST_ERROR_KEYS[result.error_code])
                  : (result.error_message ?? t("http_test_unknown_error"))
              }`,
              preview: result.response_preview ?? null
            }
      ),
    onError: (error) =>
      report({
        ok: false,
        message: `${t("http_test_failed_prefix")}: ${
          describeSaveError(
            error,
            {
              stepId,
              stepOrder: 0,
              config: { input_source: "http_get", output_mode: "http_post" }
            },
            t
          ).message
        }`,
        preview: null
      })
  });

  function run() {
    if (test.isPending) return;
    if (!config.url.trim()) {
      report({ ok: false, message: t("http_test_needs_url"), preview: null });
      return;
    }
    let testVariables: Record<string, unknown> = {};
    if (templated) {
      try {
        const parsed: unknown = JSON.parse(variables || "{}");
        if (!isJsonObject(parsed)) throw new Error("not an object");
        testVariables = parsed;
      } catch {
        setVariablesProblem(t("http_test_variables_invalid"));
        return;
      }
    }
    setVariablesProblem(null);
    test.mutate(testVariables);
  }

  return (
    <div className="border-ax-border rounded-ax-container flex flex-col gap-3 border p-3">
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {t("http_test_desc")}
      </Text>
      {templated && (
        <TextArea
          label={t("http_test_variables_label")}
          description={t("http_test_variables_help")}
          value={variables}
          onChange={setVariables}
          rows={3}
          hasSpellCheck={false}
          controlClassName="font-mono"
          status={problemStatus(variablesProblem)}
          width="100%"
        />
      )}
      <div>
        <Button
          label={t("http_test_button")}
          variant="secondary"
          size="sm"
          isLoading={test.isPending}
          isInterruptible
          onClick={run}
        />
      </div>
      {outcome && (
        <div className="flex flex-col gap-2">
          <p
            className={`m-0 flex items-start gap-2 text-sm ${outcome.ok ? "text-ax-success" : "text-ax-error"}`}
          >
            {outcome.ok ? (
              <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            ) : (
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            )}
            <span>{outcome.message}</span>
          </p>
          {outcome.preview && (
            <div className="flex flex-col gap-1">
              <Text id={previewId} type="label" as="p" display="block" className="m-0">
                {t("http_test_response_preview")}
              </Text>
              <pre
                role="region"
                aria-labelledby={previewId}
                tabIndex={0}
                className="bg-ax-sunken rounded-ax-inner focus-visible:outline-ring m-0 max-h-48 overflow-auto p-2 font-mono text-xs whitespace-pre-wrap focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                {outcome.preview}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The authored HTTP call of a step: what it fetches (`http_get` input) or
 * where it sends its result (`http_post` output). URL, headers and body may
 * read run values; credentials may not, and are never shown once stored.
 */
export function HttpFields({
  flowId,
  stepId,
  direction,
  config,
  onChange,
  groups,
  problem
}: {
  flowId: string;
  stepId: string;
  direction: "input" | "output";
  config: HttpConfig;
  onChange: (config: HttpConfig) => void;
  groups: VariableGroup[];
  problem?: string;
}) {
  const t = useTranslations();
  const urlId = useId();
  const [showUrlProblem, setShowUrlProblem] = useState(false);
  const urlProblem = httpUrlProblem(config.url);
  const auth = config.auth;
  const insecureWithCredentials =
    (auth.mode !== "none" || config.custom_headers.some((header) => header.secret)) &&
    /^http:\/\//i.test(config.url.trim());

  function setAuthMode(mode: HttpConfig["auth"]["mode"]) {
    if (mode === auth.mode) return;
    switch (mode) {
      case "none":
        onChange({ ...config, auth: { mode: "none" } });
        break;
      case "bearer_token":
        onChange({ ...config, auth: { mode: "bearer_token", token: "" } });
        break;
      case "api_key":
        onChange({ ...config, auth: { mode: "api_key", header_name: "X-API-Key", key: "" } });
        break;
      case "basic_auth":
        onChange({ ...config, auth: { mode: "basic_auth", username: "", password: "" } });
        break;
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <TextInput
          id={urlId}
          label={
            direction === "input"
              ? t("flow_step_editor_http_url_get")
              : t("flow_step_editor_http_url_post")
          }
          description={t("flow_step_editor_http_url_description")}
          value={config.url}
          onChange={(url) => onChange({ ...config, url })}
          onBlur={() => setShowUrlProblem(true)}
          autoComplete="off"
          isRequired
          status={problemStatus(
            problem ??
              (showUrlProblem && urlProblem === "missing"
                ? t("flow_step_editor_http_url_missing")
                : showUrlProblem && urlProblem === "invalid"
                  ? t("flow_step_editor_http_url_invalid")
                  : null)
          )}
        />
        <div>
          <VariablePicker
            groups={groups}
            onInsert={(token) =>
              onChange({ ...config, url: insertToken(config.url, token, null).text })
            }
          />
        </div>
        {insecureWithCredentials && (
          <Text type="supporting" size="sm" as="p" display="block" className="text-ax-warning m-0">
            {t("flow_step_editor_http_credentials_need_https")}
          </Text>
        )}
      </div>

      <Selector
        label={t("flow_step_editor_http_auth")}
        options={[
          { value: "none", label: t("flow_step_editor_http_auth_none") },
          { value: "bearer_token", label: t("flow_step_editor_http_auth_bearer") },
          { value: "api_key", label: t("flow_step_editor_http_auth_api_key") },
          { value: "basic_auth", label: t("flow_step_editor_http_auth_basic") }
        ]}
        value={auth.mode}
        onChange={(value) => setAuthMode(value as HttpConfig["auth"]["mode"])}
      />
      {auth.mode === "bearer_token" && (
        <SecretField
          label={t("flow_step_editor_http_token")}
          value={auth.token}
          onChange={(token) => onChange({ ...config, auth: { ...auth, token } })}
        />
      )}
      {auth.mode === "api_key" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput
            label={t("flow_step_editor_http_api_key_header")}
            value={auth.header_name}
            onChange={(header_name) => onChange({ ...config, auth: { ...auth, header_name } })}
            autoComplete="off"
            isRequired
          />
          <SecretField
            label={t("flow_step_editor_http_api_key")}
            value={auth.key}
            onChange={(key) => onChange({ ...config, auth: { ...auth, key } })}
          />
        </div>
      )}
      {auth.mode === "basic_auth" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput
            label={t("flow_step_editor_http_username")}
            value={auth.username}
            onChange={(username) => onChange({ ...config, auth: { ...auth, username } })}
            autoComplete="off"
            isRequired
          />
          <SecretField
            label={t("flow_step_editor_http_password")}
            value={auth.password}
            onChange={(password) => onChange({ ...config, auth: { ...auth, password } })}
          />
        </div>
      )}

      <div className="flex flex-col gap-2">
        <Text type="label" as="p" display="block" className="m-0">
          {t("flow_step_editor_http_headers")}
        </Text>
        {config.custom_headers.length > 0 && (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {config.custom_headers.map((header, index) => (
              <HeaderRow
                // Headers have no identity of their own; their place is it.
                key={index}
                header={header}
                index={index}
                onChange={(next) =>
                  onChange({
                    ...config,
                    custom_headers: config.custom_headers.map((candidate, at) =>
                      at === index ? next : candidate
                    )
                  })
                }
                onRemove={() =>
                  onChange({
                    ...config,
                    custom_headers: config.custom_headers.filter((_, at) => at !== index)
                  })
                }
              />
            ))}
          </ul>
        )}
        <div>
          <Button
            label={t("flow_step_editor_http_header_add")}
            variant="secondary"
            size="sm"
            icon={<Plus className="size-4" aria-hidden="true" />}
            onClick={() =>
              onChange({
                ...config,
                custom_headers: [...config.custom_headers, { name: "", value: "", secret: false }]
              })
            }
          />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <NumberInput
          label={t("flow_step_editor_http_timeout")}
          value={config.timeout_seconds}
          onChange={(value) => onChange({ ...config, timeout_seconds: value ?? 30 })}
          min={1}
          isIntegerOnly
          units={t("flow_step_editor_seconds_unit")}
        />
        {direction === "input" && (
          <Selector
            label={t("flow_step_editor_http_response_format")}
            options={[
              { value: "text", label: t("flow_type_text") },
              { value: "json", label: t("flow_type_json") }
            ]}
            value={config.response_format ?? "text"}
            onChange={(value) =>
              onChange({ ...config, response_format: value === "json" ? "json" : "text" })
            }
          />
        )}
        {direction === "output" && (
          <Selector
            label={t("flow_step_editor_http_body")}
            options={[
              { value: "auto", label: t("flow_step_editor_http_body_auto") },
              { value: "json_template", label: t("flow_step_editor_http_body_json") },
              { value: "text_template", label: t("flow_step_editor_http_body_text") },
              { value: "none", label: t("flow_step_editor_http_body_none") }
            ]}
            value={config.body.mode}
            onChange={(value) =>
              onChange({ ...config, body: { ...config.body, mode: value as HttpBodyMode } })
            }
          />
        )}
      </div>
      {direction === "output" &&
        (config.body.mode === "json_template" || config.body.mode === "text_template") && (
          <TemplateTextArea
            label={t("flow_step_editor_http_body_template")}
            description={t("flow_step_editor_http_body_template_description")}
            value={config.body.template ?? ""}
            onChange={(template) => onChange({ ...config, body: { ...config.body, template } })}
            groups={groups}
            rows={6}
            code
          />
        )}
      <HttpTest flowId={flowId} stepId={stepId} direction={direction} config={config} />
    </div>
  );
}
