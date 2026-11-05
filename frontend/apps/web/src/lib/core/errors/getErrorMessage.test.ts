import { EneoError, type EneoErrorCode } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";
import en from "../../../../messages/en.json";
import sv from "../../../../messages/sv.json";

vi.mock("$lib/paraglide/messages", () => ({
  m: {
    eneo_error_9008: () => "Usage quota exceeded.",
    eneo_error_9010: () => "The AI service is temporarily unavailable.",
    eneo_error_9042: () => "Credential encryption must be configured before saving secrets.",
    eneo_error_9048: () => "Slug taken.",
    eneo_error_9049: () => "Published Skills are kept.",
    eneo_error_9050: () => "An App run needs it.",
    eneo_error_9051: () => "Still attached.",
    eneo_error_9052: () => "The execution block changed.",
    eneo_error_9057: () => "Original unavailable.",
    eneo_error_9058: () => "Choose a different password.",
    eneo_error_9059: () => "Password policy violation.",
    eneo_error_9062: () => "Skill removal busy.",
    eneo_error_9063: () => "Active website sync.",
    eneo_error_9064: () => "Crawler cleanup pending.",
    eneo_error_9069: () => "Deactivate it in the governance first.",
    eneo_error_9070: () => "Choose a new password before continuing.",
    eneo_error_9071: () => "Archive the widget before moving the assistant.",
    chat_answer_failed_internal: () => "An error in Eneo interrupted the answer.",
    provider_failure_unavailable: () => "The provider is having problems.",
    provider_failure_timeout: () => "The model did not respond in time.",
    provider_failure_unreachable: () => "Could not connect to the provider.",
    provider_failure_connection_lost: () => "The connection was lost.",
    provider_failure_rate_limited: () => "A usage limit was reached.",
    provider_failure_model_not_found: () => "The provider does not offer this model.",
    provider_failure_rejected_request: () => "The provider rejected the request.",
    job_failure_tenant_quota_exceeded: () => "The organization's quota is full.",
    job_failure_user_quota_exceeded: () => "Your quota is full.",
    integration_error_credentials_invalid: () => "The organization's sign-in was refused.",
    integration_error_oauth_code_rejected: () => "Start the sign-in again.",
    integration_error_oauth_client_rejected: () => "Check the app's secret.",
    integration_error_syncing: () => "Try again after the sync.",
    request_failed: () => "Request failed."
  }
}));

import { getErrorMessage } from "./getErrorMessage";

/** Reason codes for the Skill lifecycle conflicts, and the code that used to
    answer for all of them: a taken name. */
const SKILL_CONFLICT_CODES = [9048, 9049, 9050, 9051, 9052] as const;
const NAME_COLLISION = 9017;

describe("getErrorMessage", () => {
  it("distinguishes a published widget from a required password change", () => {
    expect(getErrorMessage(new EneoError("Fallback", "RESPONSE", 409, 9071))).toBe(
      "Archive the widget before moving the assistant."
    );
    expect(getErrorMessage(new EneoError("Fallback", "RESPONSE", 403, 9070))).toBe(
      "Choose a new password before continuing."
    );
    for (const catalogue of [en, sv]) {
      expect(catalogue.eneo_error_9071).toBeTruthy();
      expect(catalogue.eneo_error_9071).not.toBe(catalogue.eneo_error_9070);
    }
  });

  it("localizes missing credential encryption configuration", () => {
    const error = new EneoError(
      "Backend fallback",
      "RESPONSE",
      503,
      9042,
      {},
      { endpoint: "POST@/api/v1/admin/model-providers/" }
    );

    expect(getErrorMessage(error)).toBe(
      "Credential encryption must be configured before saving secrets."
    );
  });

  it("gives every Skill lifecycle conflict its own localized recovery instruction", () => {
    const localized = Object.fromEntries(
      SKILL_CONFLICT_CODES.map((code) => [
        code,
        getErrorMessage(
          // An unmapped code falls back to this backend text, so seeing it
          // here means the conflict never reached the localization table.
          new EneoError("Backend fallback", "RESPONSE", 409, code, {}, { endpoint: "" })
        )
      ])
    );

    expect(localized).toEqual({
      9048: "Slug taken.",
      9049: "Published Skills are kept.",
      9050: "An App run needs it.",
      9051: "Still attached.",
      9052: "The execution block changed."
    });
  });

  it("says what blocks deleting a prompt the governance uses", () => {
    const error = new EneoError(
      "Prompt 'Standard' is referenced by the personal assistant governance policy.",
      "RESPONSE",
      409,
      9069,
      {},
      { endpoint: "DELETE@/api/v1/admin/prompt-library/p1/" }
    );

    expect(getErrorMessage(error)).toBe("Deactivate it in the governance first.");
    for (const catalogue of [en, sv] as Record<string, string>[]) {
      // Its own copy: it used to arrive as a taken name (9017).
      expect(catalogue.eneo_error_9069).toBeTruthy();
      expect(catalogue.eneo_error_9069).not.toBe(catalogue.eneo_error_9017);
    }
  });

  it("never answers a Skill conflict with the taken-name copy", () => {
    for (const catalogue of [en, sv] as Record<string, string>[]) {
      const takenNameCopy = catalogue[`eneo_error_${NAME_COLLISION}`];
      expect(takenNameCopy).toBeTruthy();

      for (const code of SKILL_CONFLICT_CODES) {
        const skillCopy = catalogue[`eneo_error_${code}`];
        expect(skillCopy, `eneo_error_${code}`).toBeTruthy();
        expect(skillCopy).not.toBe(takenNameCopy);
      }
    }
  });

  it("words a taken name for every resource that answers with it, not only models", () => {
    // Providers, MCP servers, templates, files, modules and models send 9017.
    expect(en[`eneo_error_${NAME_COLLISION}`]).toBe(
      "This name is already in use. Choose a different one."
    );
    expect(sv[`eneo_error_${NAME_COLLISION}`]).toBe("Namnet används redan. Välj ett annat namn.");
  });

  it("names an integration refusal in the viewer's language, keeping Microsoft's code", () => {
    const refusal = (code: string, message: string, status = 400) =>
      new EneoError(
        message,
        "RESPONSE",
        status,
        9007,
        { eneo_error_code: 9007, code, message },
        { endpoint: "" }
      );

    expect(
      getErrorMessage(
        refusal("sharepoint_credentials_invalid", "SharePoint credentials are invalid")
      )
    ).toBe("The organization's sign-in was refused.");
    expect(
      getErrorMessage(
        refusal("oauth_code_rejected", "Microsoft did not accept the code (AADSTS70008).")
      )
    ).toBe("Start the sign-in again. (AADSTS70008)");
    expect(getErrorMessage(refusal("oauth_client_rejected", "Refused (AADSTS7000215)."))).toBe(
      "Check the app's secret. (AADSTS7000215)"
    );
    expect(getErrorMessage(refusal("integration_knowledge_syncing", "Syncing", 409))).toBe(
      "Try again after the sync."
    );
  });

  it("tells the user on whose side an answer failed", () => {
    const httpError = (code: string, eneoCode: EneoErrorCode = 9010) =>
      new EneoError(
        "AI service is temporarily unavailable. Please try again later.",
        "RESPONSE",
        503,
        eneoCode,
        { eneo_error_code: eneoCode, code, details: { reason: code } },
        { endpoint: "STREAM@/api/v1/conversations/" }
      );
    // The stream's error event arrives after HTTP 200 and carries no Eneo code.
    const streamError = (code: string) =>
      new EneoError("Backend fallback", "SERVER", 200, 0, { code, message: "Backend fallback" });

    expect(getErrorMessage(httpError("provider_unavailable"))).toBe(
      "The provider is having problems."
    );
    expect(getErrorMessage(httpError("provider_timeout"))).toBe(
      "The model did not respond in time."
    );
    expect(getErrorMessage(httpError("provider_unreachable"))).toBe(
      "Could not connect to the provider."
    );
    expect(getErrorMessage(httpError("provider_rate_limited"))).toBe("A usage limit was reached.");
    expect(getErrorMessage(httpError("provider_model_not_found"))).toBe(
      "The provider does not offer this model."
    );
    expect(getErrorMessage(httpError("provider_rejected_request", 9041))).toBe(
      "The provider rejected the request."
    );
    expect(getErrorMessage(streamError("provider_connection_lost"))).toBe(
      "The connection was lost."
    );
    expect(getErrorMessage(streamError("stream_error"))).toBe(
      "An error in Eneo interrupted the answer."
    );
    // An unclassified provider failure keeps the general 9010 copy.
    expect(getErrorMessage(httpError("provider_error"))).toBe(
      "The AI service is temporarily unavailable."
    );
    expect(getErrorMessage(streamError("provider_error"))).toBe(
      "The AI service is temporarily unavailable."
    );
  });

  it("keeps every answer failure message in both catalogues", () => {
    const keys = [
      "provider_failure_unavailable",
      "provider_failure_timeout",
      "provider_failure_unreachable",
      "provider_failure_connection_lost",
      "provider_failure_rate_limited",
      "provider_failure_model_not_found",
      "provider_failure_rejected_request",
      "chat_answer_failed_internal",
      "chat_answer_failed"
    ];
    for (const catalogue of [en, sv] as Record<string, string>[]) {
      for (const key of keys) {
        expect(catalogue[key]?.trim(), key).toBeTruthy();
      }
    }
  });

  it("tells the user which storage quota refused the write", () => {
    const quotaError = (code?: string) =>
      new EneoError(
        "Quota limit exceeded.",
        "RESPONSE",
        403,
        9008,
        code ? { eneo_error_code: 9008, code } : { eneo_error_code: 9008 },
        { endpoint: "POST@/api/v1/groups/1/info-blobs/" }
      );

    expect(getErrorMessage(quotaError("tenant_quota_exceeded"))).toBe(
      "The organization's quota is full."
    );
    expect(getErrorMessage(quotaError("user_quota_exceeded"))).toBe("Your quota is full.");
    // A rate limit or an older backend sends 9008 without a reason code.
    expect(getErrorMessage(quotaError())).toBe("Usage quota exceeded.");
  });

  it("keeps original-download, password, skill removal and crawler lifecycle errors distinct", () => {
    const messages = ([9057, 9058, 9059, 9062, 9063, 9064] as const).map((code) =>
      getErrorMessage(
        new EneoError("Backend fallback", "RESPONSE", 409, code, {}, { endpoint: "" })
      )
    );

    expect(messages).toEqual([
      "Original unavailable.",
      "Choose a different password.",
      "Password policy violation.",
      "Skill removal busy.",
      "Active website sync.",
      "Crawler cleanup pending."
    ]);
  });
});
