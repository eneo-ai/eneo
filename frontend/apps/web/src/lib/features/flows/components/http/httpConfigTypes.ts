export type HttpAuthMode = "none" | "bearer_token" | "api_key" | "basic_auth";

export interface HttpAuthNone {
  mode: "none";
}
export interface HttpAuthBearer {
  mode: "bearer_token";
  token: string | SecretSentinel;
}
export interface HttpAuthApiKey {
  mode: "api_key";
  header_name: string;
  key: string | SecretSentinel;
}
export interface HttpAuthBasicAuth {
  mode: "basic_auth";
  username: string;
  password: string | SecretSentinel;
}
export type HttpAuth = HttpAuthNone | HttpAuthBearer | HttpAuthApiKey | HttpAuthBasicAuth;

export interface SecretSentinel {
  $secret: "stored";
}
export type SecretValue = string | SecretSentinel;

export function isSecretSentinel(value: unknown): value is SecretSentinel {
  return isRecord(value) && value.$secret === "stored";
}

export type HttpBodyMode = "auto" | "json_template" | "text_template" | "none";
export interface HttpBody {
  mode: HttpBodyMode;
  template?: string | null;
}

export interface CustomHeader {
  name: string;
  value: SecretValue;
  secret: boolean;
}

export interface HttpAuthoredConfig {
  url: string;
  auth: HttpAuth;
  timeout_seconds: number;
  body: HttpBody;
  custom_headers: CustomHeader[];
  response_format?: "text" | "json" | null;
}

export type HttpDirection = "input" | "output";
export type HttpMethod = "GET" | "POST";

export function parseHttpAuthoredConfig(
  value: unknown,
  defaults: HttpAuthoredConfig
): HttpAuthoredConfig {
  const record = isRecord(value) ? value : {};
  return {
    url: stringOrDefault(record.url, defaults.url),
    auth: parseHttpAuth(record.auth, defaults.auth),
    timeout_seconds: numberOrDefault(record.timeout_seconds, defaults.timeout_seconds),
    body: parseHttpBody(record.body, defaults.body),
    custom_headers: parseCustomHeaders(record.custom_headers, defaults.custom_headers),
    response_format: parseResponseFormat(record.response_format, defaults.response_format ?? null)
  };
}

function parseHttpAuth(value: unknown, defaults: HttpAuth): HttpAuth {
  if (!isRecord(value) || typeof value.mode !== "string") {
    return cloneHttpAuth(defaults);
  }

  if (value.mode === "bearer_token") {
    const defaultToken = defaults.mode === "bearer_token" ? defaults.token : "";
    return {
      mode: "bearer_token",
      token: secretValueOrDefault(value.token, defaultToken)
    };
  }

  if (value.mode === "api_key") {
    const defaultHeaderName = defaults.mode === "api_key" ? defaults.header_name : "";
    const defaultKey = defaults.mode === "api_key" ? defaults.key : "";
    return {
      mode: "api_key",
      header_name: stringOrDefault(value.header_name, defaultHeaderName),
      key: secretValueOrDefault(value.key, defaultKey)
    };
  }

  if (value.mode === "basic_auth") {
    const defaultUsername = defaults.mode === "basic_auth" ? defaults.username : "";
    const defaultPassword = defaults.mode === "basic_auth" ? defaults.password : "";
    return {
      mode: "basic_auth",
      username: stringOrDefault(value.username, defaultUsername),
      password: secretValueOrDefault(value.password, defaultPassword)
    };
  }

  if (value.mode === "none") {
    return { mode: "none" };
  }

  return cloneHttpAuth(defaults);
}

function parseHttpBody(value: unknown, defaults: HttpBody): HttpBody {
  if (!isRecord(value)) {
    return cloneHttpBody(defaults);
  }

  const mode = isHttpBodyMode(value.mode) ? value.mode : defaults.mode;
  const template =
    typeof value.template === "string" || value.template === null
      ? value.template
      : defaults.template;
  return template === undefined ? { mode } : { mode, template };
}

function parseCustomHeaders(value: unknown, defaults: CustomHeader[]): CustomHeader[] {
  if (!Array.isArray(value)) {
    return defaults.map(cloneCustomHeader);
  }

  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    return [
      {
        name: stringOrDefault(item.name, ""),
        value: secretValueOrDefault(item.value, ""),
        secret: booleanOrDefault(item.secret, false)
      }
    ];
  });
}

function parseResponseFormat(
  value: unknown,
  defaultValue: HttpAuthoredConfig["response_format"]
): HttpAuthoredConfig["response_format"] {
  if (value === "text" || value === "json" || value === null) return value;
  return defaultValue;
}

function cloneHttpAuth(auth: HttpAuth): HttpAuth {
  if (auth.mode === "bearer_token") {
    return { mode: "bearer_token", token: cloneSecretValue(auth.token) };
  }
  if (auth.mode === "api_key") {
    return {
      mode: "api_key",
      header_name: auth.header_name,
      key: cloneSecretValue(auth.key)
    };
  }
  if (auth.mode === "basic_auth") {
    return {
      mode: "basic_auth",
      username: auth.username,
      password: cloneSecretValue(auth.password)
    };
  }
  return { mode: "none" };
}

function cloneHttpBody(body: HttpBody): HttpBody {
  return body.template === undefined
    ? { mode: body.mode }
    : { mode: body.mode, template: body.template };
}

function cloneCustomHeader(header: CustomHeader): CustomHeader {
  return {
    name: header.name,
    value: cloneSecretValue(header.value),
    secret: header.secret
  };
}

function cloneSecretValue(value: SecretValue): SecretValue {
  return isSecretSentinel(value) ? { $secret: "stored" } : value;
}

function secretValueOrDefault(value: unknown, defaultValue: SecretValue): SecretValue {
  if (typeof value === "string") return value;
  if (isSecretSentinel(value)) return { $secret: "stored" };
  return cloneSecretValue(defaultValue);
}

function stringOrDefault(value: unknown, defaultValue: string): string {
  return typeof value === "string" ? value : defaultValue;
}

function numberOrDefault(value: unknown, defaultValue: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : defaultValue;
}

function booleanOrDefault(value: unknown, defaultValue: boolean): boolean {
  return typeof value === "boolean" ? value : defaultValue;
}

function isHttpBodyMode(value: unknown): value is HttpBodyMode {
  return (
    value === "auto" || value === "json_template" || value === "text_template" || value === "none"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
