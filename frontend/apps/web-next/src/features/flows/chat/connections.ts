import type { FieldAnchor } from "../editor/field-problems";
import { isSecretSentinel, readHttpConfig, type HttpConfig } from "../editor/step-configs";
import type { FlowStep } from "../editor/step-types";

/**
 * A service a step talks to, as the chat's step card shows it: where it goes,
 * how it signs in, and whether what it needs is stored. The secret itself is
 * never read here; the editor field (`anchor`) is where the person enters it.
 */
export type StepConnection = {
  direction: "input" | "output";
  anchor: FieldAnchor;
  /** The address's host, or the whole address when it is not a URL yet. */
  host: string;
  authMode: HttpConfig["auth"]["mode"];
  /** Whether the address is set and every credential the auth mode and secret headers need is stored. */
  configured: boolean;
};

function hostOf(url: string): string {
  try {
    return new URL(url.trim()).host;
  } catch {
    return url.trim();
  }
}

function credentialOf(auth: HttpConfig["auth"]): unknown {
  switch (auth.mode) {
    case "bearer_token":
      return auth.token;
    case "api_key":
      return auth.key;
    case "basic_auth":
      return auth.password;
    default:
      return null;
  }
}

const stored = (value: unknown) =>
  isSecretSentinel(value) || (typeof value === "string" && value.length > 0);

function connectionOf(
  config: unknown,
  direction: StepConnection["direction"],
  anchor: FieldAnchor
): StepConnection {
  const http = readHttpConfig(config, direction);
  const credential = credentialOf(http.auth);
  const secretsStored =
    (http.auth.mode === "none" || stored(credential)) &&
    http.custom_headers.filter((header) => header.secret).every((header) => stored(header.value));
  return {
    direction,
    anchor,
    host: hostOf(http.url),
    authMode: http.auth.mode,
    configured: http.url.trim().length > 0 && secretsStored
  };
}

/** The HTTP services a step reads from or delivers to; empty for a step without one. */
export function stepConnections(
  step: Pick<FlowStep, "input_source" | "input_config" | "output_mode" | "output_config">
): StepConnection[] {
  const connections: StepConnection[] = [];
  if (step.input_source === "http_get") {
    connections.push(connectionOf(step.input_config, "input", "input_config.http"));
  }
  if (step.output_mode === "http_post") {
    connections.push(connectionOf(step.output_config, "output", "output_config.http"));
  }
  return connections;
}

/** The connection "Anslut tjänst" opens: the first one not yet configured, else the first. */
export function connectionToOpen(connections: StepConnection[]): StepConnection | null {
  return connections.find((connection) => !connection.configured) ?? connections[0] ?? null;
}
