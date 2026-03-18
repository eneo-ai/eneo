// Auth types
export type HttpAuthMode = "none" | "bearer_token" | "api_key" | "basic_auth";

export interface HttpAuthNone { mode: "none" }
export interface HttpAuthBearer { mode: "bearer_token"; token: string | SecretSentinel }
export interface HttpAuthApiKey { mode: "api_key"; header_name: string; key: string | SecretSentinel }
export interface HttpAuthBasicAuth { mode: "basic_auth"; username: string; password: string | SecretSentinel }
export type HttpAuth = HttpAuthNone | HttpAuthBearer | HttpAuthApiKey | HttpAuthBasicAuth;

// Secret sentinel
export interface SecretSentinel { $secret: "stored" }
export type SecretValue = string | SecretSentinel;

export function isSecretSentinel(value: unknown): value is SecretSentinel {
  return typeof value === "object" && value !== null && "$secret" in value && (value as any).$secret === "stored";
}

// Body types
export type HttpBodyMode = "auto" | "json_template" | "text_template" | "none";
export interface HttpBody {
  mode: HttpBodyMode;
  template?: string | null;
}

// Custom header
export interface CustomHeader {
  name: string;
  value: SecretValue;
  secret: boolean;
}

// Full authored config
export interface HttpAuthoredConfig {
  url: string;
  auth: HttpAuth;
  timeout_seconds: number;
  body: HttpBody;
  custom_headers: CustomHeader[];
  response_format?: "text" | "json" | null;
}

// Context types
export type HttpDirection = "input" | "output";
export type HttpMethod = "GET" | "POST";
