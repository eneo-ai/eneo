import { createEneo, EneoError } from "@eneo/eneo-js";
import { fail, type RequestEvent } from "@sveltejs/kit";
import {
  FEDERATION_FIELDS,
  patchFromForm,
  type FederationField,
  type FederationView
} from "$lib/features/federation/federationDraft";
import type { Actions, PageServerLoad } from "./$types";

/** What the page shows. The load never rejects, so the page always has a state. */
export type FederationState =
  | { kind: "ready"; view: FederationView }
  | { kind: "unconfigured" }
  | { kind: "disabled" }
  | { kind: "error" };

/** Why a save failed: codes only, never a submitted value such as the secret. */
export type SaveFailure =
  | { code: "conflict" | "not_configured" | "disabled" | "encryption_unavailable" }
  | { code: "request_failed" }
  | { code: "endpoint_host"; host: string }
  | { code: "fields"; fields: Partial<Record<FederationField, "refused" | "secret_masked">> };

function eneo(event: Pick<RequestEvent, "fetch" | "locals">) {
  return createEneo({
    token: event.locals.id_token ?? undefined,
    baseUrl: event.locals.environment.baseUrl ?? "",
    fetch: event.fetch
  });
}

/** The backend's reason code, `{"detail": {"code": ...}}`. */
function reason(error: unknown): string | undefined {
  if (!(error instanceof EneoError)) return undefined;
  const detail = (error.response as { detail?: unknown } | undefined)?.detail;
  if (typeof detail !== "object" || detail === null || Array.isArray(detail)) return undefined;
  const code = (detail as { code?: unknown }).code;
  return typeof code === "string" ? code : undefined;
}

/** The fields a 422 names (`loc: ["body", field, ...]`); its input is never echoed. */
function refusedFields(error: EneoError): SaveFailure | undefined {
  const detail = (error.response as { detail?: unknown } | undefined)?.detail;
  if (!Array.isArray(detail)) return undefined;
  const fields: Partial<Record<FederationField, "refused">> = {};
  for (const item of detail) {
    const field = (item as { loc?: unknown[] } | null)?.loc?.[1];
    if (FEDERATION_FIELDS.includes(field as FederationField)) {
      fields[field as FederationField] = "refused";
    }
  }
  return Object.keys(fields).length ? { code: "fields", fields } : undefined;
}

/**
 * The provider's token endpoint or signing keys are on a host the operator has
 * not listed (a name or an IPv6 literal). The text is the backend's
 * (`check_endpoint_hosts` in `authentication/oidc/profile.py`); only the host
 * is taken from it, so no other text of a refusal is shown.
 */
const ENDPOINT_HOST =
  /^The (?:token endpoint|JWKS URI) is on ([A-Za-z0-9.:-]+), which is neither the discovery host nor in allowed_endpoint_hosts$/;

function refusedHost(error: EneoError): SaveFailure | undefined {
  const body = error.response as { message?: unknown; detail?: unknown } | undefined;
  for (const text of [body?.message, body?.detail]) {
    const host = typeof text === "string" ? ENDPOINT_HOST.exec(text)?.[1] : undefined;
    if (host) return { code: "endpoint_host", host };
  }
  return undefined;
}

const REASONS: Record<string, SaveFailure> = {
  federation_config_revision_conflict: { code: "conflict" },
  federation_not_configured: { code: "not_configured" },
  federation_disabled: { code: "disabled" },
  federation_encryption_unavailable: { code: "encryption_unavailable" },
  federation_secret_looks_masked: { code: "fields", fields: { client_secret: "secret_masked" } }
};

function saveFailure(error: unknown): SaveFailure {
  const known = REASONS[reason(error) ?? ""];
  if (known) return known;
  if (error instanceof EneoError && error.status === 422) {
    return refusedFields(error) ?? { code: "request_failed" };
  }
  if (error instanceof EneoError && error.status === 400) {
    return refusedHost(error) ?? { code: "request_failed" };
  }
  return { code: "request_failed" };
}

async function readFederation(event: Pick<RequestEvent, "fetch" | "locals">) {
  try {
    const view = await eneo(event).federation.get();
    return view.configured
      ? ({ kind: "ready", view } satisfies FederationState)
      : ({ kind: "unconfigured" } satisfies FederationState);
  } catch (error) {
    return reason(error) === "federation_disabled"
      ? ({ kind: "disabled" } satisfies FederationState)
      : ({ kind: "error" } satisfies FederationState);
  }
}

export const load: PageServerLoad = (event) => {
  event.depends("admin:federation");
  return { federation: readFederation(event) as Promise<FederationState> };
};

export const actions: Actions = {
  save: async (event) => {
    const patch = patchFromForm(await event.request.formData());
    if (!patch) return fail(400, { failure: { code: "request_failed" } as SaveFailure });
    try {
      return { view: await eneo(event).federation.update(patch) };
    } catch (error) {
      // Caught here so the secret in the request never reaches the error logs.
      const status =
        error instanceof EneoError && error.status >= 400 && error.status < 600
          ? error.status
          : 500;
      return fail(status, { failure: saveFailure(error) });
    }
  }
};
