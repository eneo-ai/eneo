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
import { Collapsible } from "@/components/astryx/collapsible";
import { TextInput } from "@/components/astryx/text-input";
import { tokensOf } from "../flow-steps";
import { isJsonObject } from "./step-types";
import { testHttp, type HttpTestResponse } from "./editor-api";
import { Anchor, FieldMessage, problemStatus, VariablePicker } from "./editor-fields";
import { TemplateTextArea } from "./reference-text-area";
import { describeSaveError, HTTP_ERROR_KEYS, type FieldProblems } from "./field-problems";
import {
  headerSent,
  httpUrlProblem,
  isSecretSentinel,
  type HttpBodyMode,
  type HttpConfig,
  type HttpHeader,
  type SecretValue
} from "./step-configs";
import { httpAuthModeLabel, httpBodyModeLabel } from "./step-labels";
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
  // The core leaves a row without a name out of the request.
  const unnamed = !header.name.trim() && header.value !== "";
  return (
    <li className="border-ax-border rounded-ax-element flex flex-col gap-3 border p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <TextInput
          label={t("flow_step_editor_http_header_name", { index: index + 1 })}
          value={header.name}
          onChange={(name) => onChange({ ...header, name })}
          autoComplete="off"
          status={
            unnamed
              ? { type: "warning", message: t("flow_step_editor_http_header_name_missing") }
              : undefined
          }
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

type Translate = ReturnType<typeof useTranslations>;

/** What a failed test says to change; a status code names the likely cause. */
function testFailure(result: HttpTestResponse, t: Translate): string {
  const status = result.status_code;
  if (result.error_code === "HTTP_STATUS_ERROR" && status) {
    if (status === 401 || status === 403) return t("http_test_status_auth", { status });
    if (status === 404) return t("http_test_status_not_found", { status });
    return t("http_test_status_error", { status });
  }
  const key = result.error_code ? HTTP_ERROR_KEYS[result.error_code] : undefined;
  return key ? t(key) : (result.error_message ?? t("http_test_unknown_error"));
}

/**
 * The test values to fill in: an empty value for each reference the call reads,
 * nested as the reference names it (`{{step_1.output}}` is `step_1` › `output`).
 */
export function sampleTestVariables(config: HttpConfig): string {
  // Without a prototype, a reference named `__proto__` is a key like any other.
  const sample: Record<string, unknown> = Object.create(null);
  for (const token of tokensOf(JSON.stringify(config))) {
    const path = token.split(".");
    let node = sample;
    path.forEach((key, index) => {
      if (index === path.length - 1) {
        if (!(key in node)) node[key] = "";
        return;
      }
      const next = node[key];
      if (typeof next !== "object" || next === null) node[key] = Object.create(null);
      node = node[key] as Record<string, unknown>;
    });
  }
  return JSON.stringify(sample, null, 2);
}

type TestOutcome = {
  ok: boolean;
  title: string;
  detail: string | null;
  preview: string | null;
};

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
  // Follows the call's references until the author edits it.
  const [editedVariables, setVariables] = useState<string | null>(null);
  const variables = editedVariables ?? sampleTestVariables(config);
  const [variablesProblem, setVariablesProblem] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<TestOutcome | null>(null);
  const templated = JSON.stringify(config).includes("{{");

  function report(next: TestOutcome) {
    setOutcome(next);
    announce(next.detail ? `${next.title}. ${next.detail}` : next.title);
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
              title: result.status_code
                ? `${t("http_test_success")} (${result.status_code})`
                : t("http_test_success"),
              detail: null,
              preview: result.response_preview ?? null
            }
          : {
              ok: false,
              title: t("http_test_failed_prefix"),
              detail: testFailure(result, t),
              preview: result.response_preview ?? null
            }
      ),
    onError: (error) =>
      report({
        ok: false,
        title: t("http_test_failed_prefix"),
        detail: describeSaveError(
          error,
          {
            stepId,
            stepOrder: 0,
            config: { input_source: "http_get", output_mode: "http_post" }
          },
          t
        ).message,
        preview: null
      })
  });

  function run() {
    if (test.isPending) return;
    if (!config.url.trim()) {
      report({ ok: false, title: t("http_test_needs_url"), detail: null, preview: null });
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
    <div className="border-ax-border flex flex-col gap-3 border-t pt-4">
      <Text
        type="supporting"
        size="sm"
        as="p"
        display="block"
        className="m-0 max-w-prose text-pretty"
      >
        {t(direction === "input" ? "http_test_desc_input" : "http_test_desc_output")}
      </Text>
      {templated && (
        <TextArea
          label={t("http_test_variables_label")}
          description={t("http_test_variables_help")}
          value={variables}
          onChange={setVariables}
          rows={Math.min(8, Math.max(3, variables.split("\n").length))}
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
            <span className="flex flex-col gap-0.5">
              <span className="font-semibold">{outcome.title}</span>
              {outcome.detail && <span>{outcome.detail}</span>}
            </span>
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
  formId,
  flowId,
  stepId,
  direction,
  config,
  onChange,
  groups,
  problems
}: {
  formId: string;
  flowId: string;
  stepId: string;
  direction: "input" | "output";
  config: HttpConfig;
  onChange: (config: HttpConfig) => void;
  groups: VariableGroup[];
  problems: FieldProblems;
}) {
  const t = useTranslations();
  // A refused save lands at the part it is about (`field-problems.ts`).
  const base = direction === "input" ? "input_config.http" : "output_config.http";
  const problem = problems[base];
  const authProblem = problems[`${base}.auth`];
  const bodyProblem = direction === "output" ? problems["output_config.http.body"] : undefined;
  const moreProblem = problems[`${base}.more`];
  const bodyTemplated =
    config.body.mode === "json_template" || config.body.mode === "text_template";
  const urlId = useId();
  const moreId = useId();
  const [showUrlProblem, setShowUrlProblem] = useState(false);
  const urlProblem = httpUrlProblem(config.url);
  const auth = config.auth;
  const url = config.url.trim();
  // The core sends a credential only to https:// with the host written out.
  const insecureWithCredentials =
    (auth.mode !== "none" ||
      config.custom_headers.some((header) => header.secret && headerSent(header))) &&
    url !== "" &&
    !/^https:\/\/[^/?#{]+(?:[/?#]|$)/i.test(url);
  const localUrlProblem = !showUrlProblem
    ? null
    : urlProblem === "missing"
      ? t("flow_step_editor_http_url_missing")
      : urlProblem === "invalid"
        ? t("flow_step_editor_http_url_invalid")
        : null;
  const urlError = problem ?? localUrlProblem;

  const inUse =
    config.custom_headers.filter(headerSent).length + (config.timeout_seconds !== 30 ? 1 : 0);
  // Folded while the defaults hold; settings in use open it.
  const [moreOpen, setMoreOpen] = useState(inUse > 0);

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
          onChange={(next) => onChange({ ...config, url: next })}
          onBlur={() => setShowUrlProblem(true)}
          autoComplete="off"
          isRequired
          status={
            urlError
              ? { type: "error", message: urlError }
              : insecureWithCredentials
                ? // The core refuses to save it: an error, not a warning.
                  { type: "error", message: t("flow_step_editor_http_credentials_need_https") }
                : undefined
          }
        />
        <div>
          <VariablePicker
            groups={groups}
            onInsert={(token) =>
              onChange({ ...config, url: insertToken(config.url, token, null).text })
            }
          />
        </div>
      </div>

      <Anchor formId={formId} anchor={`${base}.auth`} className="flex flex-col gap-4">
        <Selector
          label={t("flow_step_editor_http_auth")}
          options={(["none", "bearer_token", "api_key", "basic_auth"] as const).map((mode) => ({
            value: mode,
            label: httpAuthModeLabel(mode, t)
          }))}
          value={auth.mode}
          onChange={(value) => setAuthMode(value as HttpConfig["auth"]["mode"])}
        />
        {auth.mode === "bearer_token" && (
          <SecretField
            label={t("flow_step_editor_http_token")}
            value={auth.token}
            onChange={(token) => onChange({ ...config, auth: { ...auth, token } })}
            status={problemStatus(authProblem)}
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
              status={problemStatus(authProblem)}
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
              status={problemStatus(authProblem)}
            />
          </div>
        )}
      </Anchor>

      {direction === "input" ? (
        <Selector
          label={t("flow_step_editor_http_response_format")}
          description={t("flow_step_editor_http_response_format_description")}
          options={[
            { value: "text", label: t("flow_type_text") },
            { value: "json", label: t("flow_type_json") }
          ]}
          value={config.response_format ?? "text"}
          onChange={(value) =>
            onChange({ ...config, response_format: value === "json" ? "json" : "text" })
          }
        />
      ) : (
        <Anchor formId={formId} anchor="output_config.http.body" className="flex flex-col gap-4">
          <Selector
            label={t("flow_step_editor_http_body")}
            description={t("flow_step_editor_http_body_description")}
            options={(["auto", "json_template", "text_template", "none"] as const).map((mode) => ({
              value: mode,
              label: httpBodyModeLabel(mode, t)
            }))}
            value={config.body.mode}
            onChange={(value) =>
              onChange({ ...config, body: { ...config.body, mode: value as HttpBodyMode } })
            }
            // With a template, the problem is shown at the template.
            status={problemStatus(bodyTemplated ? undefined : bodyProblem)}
          />
          {bodyTemplated && (
            <TemplateTextArea
              label={t("flow_step_editor_http_body_template")}
              description={t("flow_step_editor_http_body_template_description")}
              value={config.body.template ?? ""}
              onChange={(template) => onChange({ ...config, body: { ...config.body, template } })}
              groups={groups}
              rows={6}
              code
              status={problemStatus(bodyProblem)}
            />
          )}
        </Anchor>
      )}

      <Anchor formId={formId} anchor={`${base}.more`}>
        <section aria-labelledby={moreId}>
          <Collapsible
            // A refused save about a setting in here opens it.
            isOpen={moreOpen || Boolean(moreProblem)}
            onOpenChange={setMoreOpen}
            chevronPosition="start"
            trigger={
              <span className="flex flex-col gap-0.5 py-1 text-start">
                <Text id={moreId} type="label">
                  {t("flow_step_editor_http_more_title")}
                </Text>{" "}
                <Text type="supporting" size="sm">
                  {inUse > 0
                    ? t("flow_step_editor_advanced_in_use", { count: inUse })
                    : t("flow_step_editor_http_more_description")}
                </Text>
              </span>
            }
          >
            <div className="flex flex-col gap-4 pt-3">
              <FieldMessage message={moreProblem} />
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
                        custom_headers: [
                          ...config.custom_headers,
                          { name: "", value: "", secret: false }
                        ]
                      })
                    }
                  />
                </div>
              </div>
              <NumberInput
                label={t("flow_step_editor_http_timeout")}
                description={t("flow_step_editor_http_timeout_description")}
                value={config.timeout_seconds}
                onChange={(value) => onChange({ ...config, timeout_seconds: value ?? 30 })}
                // The ceiling is the deployment's (flow_http_max_timeout_seconds):
                // the core refuses a longer one on save, at this field.
                min={1}
                isIntegerOnly
                units={t("flow_step_editor_seconds_unit")}
              />
            </div>
          </Collapsible>
        </section>
      </Anchor>

      <HttpTest flowId={flowId} stepId={stepId} direction={direction} config={config} />
    </div>
  );
}
