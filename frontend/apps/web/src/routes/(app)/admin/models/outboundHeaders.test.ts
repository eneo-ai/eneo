import { describe, expect, it } from "vitest";
import type { OutboundHeaderOptions, OutboundHeaderPublic } from "@eneo/eneo-js";

import {
  canKeepStored,
  changeStored,
  headerClassification,
  headersPayload,
  insertToken,
  isRowComplete,
  isUnencryptedRemote,
  keepStored,
  newHeaderRow,
  rowsFromHeaders,
  setSecret,
  supportsOutboundHeaders,
  tokenProblems,
  tokensIn
} from "./outboundHeaders";

const MASK = "********";

const secretHeader: OutboundHeaderPublic = {
  id: "h1",
  name: "X-Credential",
  value: MASK,
  encoding: "none",
  secret: true,
  on_missing: "fallback",
  fallback: MASK
};

const plainHeader: OutboundHeaderPublic = {
  id: "h2",
  name: "X-Org-Unit",
  value: "{{user.department}}",
  encoding: "percent",
  secret: false,
  on_missing: "omit",
  fallback: null
};

const options: OutboundHeaderOptions = {
  dynamic_values: [
    {
      token: "user.employeeNumber",
      source: "scim_enterprise",
      attribute: "employeeNumber",
      classification: "identifying"
    },
    {
      token: "user.department",
      source: "scim_enterprise",
      attribute: "department",
      classification: "organisational"
    }
  ],
  supported_provider_types: ["hosted_vllm", "vllm"],
  max_headers: 10
};

describe("rowsFromHeaders", () => {
  it("never seeds a mask into the form", () => {
    const [row] = rowsFromHeaders([secretHeader]);
    expect(row.value).toBe("");
    expect(row.fallback).toBe("");
    expect(row.keepsStoredValue).toBe(true);
    expect(row.keepsStoredFallback).toBe(true);
  });

  it("seeds non-secret values", () => {
    const [row] = rowsFromHeaders([plainHeader]);
    expect(row.value).toBe("{{user.department}}");
    expect(row.keepsStoredValue).toBe(false);
  });
});

describe("headersPayload", () => {
  it("keeps a stored secret by omitting its value and fallback", () => {
    const [entry] = headersPayload(rowsFromHeaders([secretHeader]));
    expect(entry).toEqual({
      id: "h1",
      name: "X-Credential",
      encoding: "none",
      secret: true,
      on_missing: "fallback"
    });
    expect(JSON.stringify(entry)).not.toContain(MASK);
  });

  it("round-trips unchanged rows to the same entries", () => {
    const [plain] = headersPayload(rowsFromHeaders([plainHeader]));
    expect(plain).toEqual({
      id: "h2",
      name: "X-Org-Unit",
      value: "{{user.department}}",
      encoding: "percent",
      secret: false,
      on_missing: "omit",
      fallback: null
    });
  });

  it("sends a new header without an id", () => {
    const row = { ...newHeaderRow(), name: " X-Region ", value: "eu-north" };
    const [entry] = headersPayload([row]);
    expect(entry.id).toBeUndefined();
    expect(entry.name).toBe("X-Region");
    expect(entry.value).toBe("eu-north");
  });
});

describe("setSecret", () => {
  it("requires the value again when declassifying a stored secret", () => {
    const row = setSecret(rowsFromHeaders([secretHeader])[0], false);
    expect(row.keepsStoredValue).toBe(false);
    expect(row.keepsStoredFallback).toBe(false);
    expect(isRowComplete(row)).toBe(false);
  });

  it("returns to the stored secret when re-ticked before anything is typed", () => {
    const stored = rowsFromHeaders([secretHeader])[0];
    const row = setSecret(setSecret(stored, false), true);
    expect(row.keepsStoredValue).toBe(true);
    expect(row.keepsStoredFallback).toBe(true);
    expect(headersPayload([row])).toEqual(headersPayload([stored]));
  });

  it("keeps what was typed when re-ticked after typing", () => {
    const unticked = setSecret(rowsFromHeaders([secretHeader])[0], false);
    const row = setSecret({ ...unticked, value: "new-credential" }, true);
    expect(row.keepsStoredValue).toBe(false);
    expect(row.value).toBe("new-credential");
    // The fallback was not retyped, so it goes back to the stored one.
    expect(row.keepsStoredFallback).toBe(true);
  });

  it("keeps the stored value when turning secret on", () => {
    const row = setSecret(rowsFromHeaders([plainHeader])[0], true);
    expect(row.value).toBe("{{user.department}}");
    expect(row.secret).toBe(true);
  });
});

describe("changeStored / keepStored", () => {
  it("Change clears the input and Cancel returns to the stored value", () => {
    const stored = rowsFromHeaders([secretHeader])[0];
    const changed = changeStored(stored, "value");
    expect(changed.keepsStoredValue).toBe(false);
    expect(headersPayload([{ ...changed, value: "typed" }])[0].value).toBe("typed");

    expect(canKeepStored(changed, "value")).toBe(true);
    const kept = keepStored({ ...changed, value: "typed" }, "value");
    expect(kept.keepsStoredValue).toBe(true);
    expect(kept.value).toBe("");
    expect(headersPayload([kept])).toEqual(headersPayload([stored]));
  });

  it("works the same for the fallback", () => {
    const changed = changeStored(rowsFromHeaders([secretHeader])[0], "fallback");
    expect(changed.keepsStoredFallback).toBe(false);
    expect(keepStored(changed, "fallback").keepsStoredFallback).toBe(true);
  });

  it("cannot keep a stored value once the header is no longer secret", () => {
    const unticked = setSecret(rowsFromHeaders([secretHeader])[0], false);
    expect(canKeepStored(unticked, "value")).toBe(false);
    expect(keepStored(unticked, "value")).toBe(unticked);
  });

  it("has nothing to keep on a header that was never secret", () => {
    expect(canKeepStored(rowsFromHeaders([plainHeader])[0], "value")).toBe(false);
    expect(canKeepStored(newHeaderRow(), "fallback")).toBe(false);
  });
});

describe("tokens and notice", () => {
  it("finds tokens with or without inner spaces", () => {
    expect(tokensIn("{{user.division}}/{{ user.department }}")).toEqual([
      "user.division",
      "user.department"
    ]);
  });

  it("appends a token", () => {
    expect(insertToken("tier-", "user.organization")).toBe("tier-{{user.organization}}");
  });

  it("picks the highest classification in use", () => {
    const organisational = rowsFromHeaders([plainHeader]);
    expect(headerClassification(organisational, options)).toBe("organisational");
    const identifying = [
      ...organisational,
      { ...newHeaderRow(), name: "X-Employee", value: "{{user.employeeNumber}}" }
    ];
    expect(headerClassification(identifying, options)).toBe("identifying");
    expect(headerClassification([{ ...newHeaderRow(), value: "static" }], options)).toBeNull();
  });

  it("uses the server's classification for a kept secret", () => {
    const rows = rowsFromHeaders([{ ...secretHeader, classification: "identifying" }]);
    expect(headerClassification(rows, options)).toBe("identifying");
    // Once replaced, what is typed decides.
    const changed = { ...changeStored(rows[0], "value"), value: "static" };
    expect(headerClassification([changed], options)).toBeNull();
  });
});

describe("tokenProblems", () => {
  it("accepts known tokens and plain text", () => {
    expect(tokenProblems("tier-{{ user.department }}", options)).toBeNull();
    expect(tokenProblems("eu-north", options)).toBeNull();
  });

  it("names unknown tokens once", () => {
    expect(tokenProblems("{{user.departmnet}}-{{user.departmnet}}", options)).toEqual({
      unknown: ["user.departmnet"],
      malformed: false
    });
  });

  it("flags braces that do not form a token", () => {
    expect(tokenProblems("{{user.department}", options)?.malformed).toBe(true);
    expect(tokenProblems("{{user department}}", options)?.malformed).toBe(true);
  });

  it("makes the row incomplete", () => {
    const row = { ...newHeaderRow(), name: "X-A", value: "{{user.unknown}}" };
    expect(isRowComplete(row, options)).toBe(false);
    expect(isRowComplete({ ...row, value: "{{user.department}}" }, options)).toBe(true);
  });
});

describe("isUnencryptedRemote", () => {
  it("flags plain http to another host", () => {
    expect(isUnencryptedRemote("http://vllm.internal:8000/v1")).toBe(true);
    expect(isUnencryptedRemote(" HTTP://10.0.0.5/v1 ")).toBe(true);
  });

  it("exempts https, loopback and anything unparseable", () => {
    expect(isUnencryptedRemote("https://gateway.internal/v1")).toBe(false);
    expect(isUnencryptedRemote("http://localhost:4010/v1")).toBe(false);
    expect(isUnencryptedRemote("http://127.0.0.1:4010")).toBe(false);
    expect(isUnencryptedRemote("http://[::1]:8000")).toBe(false);
    expect(isUnencryptedRemote("")).toBe(false);
    expect(isUnencryptedRemote(undefined)).toBe(false);
    expect(isUnencryptedRemote("vllm.internal")).toBe(false);
  });
});

describe("supportsOutboundHeaders", () => {
  it("accepts the canonical type and its alias only", () => {
    expect(supportsOutboundHeaders(options, "hosted_vllm")).toBe(true);
    expect(supportsOutboundHeaders(options, "vllm")).toBe(true);
    expect(supportsOutboundHeaders(options, "openai")).toBe(false);
    expect(supportsOutboundHeaders(null, "hosted_vllm")).toBe(false);
  });
});

describe("isRowComplete", () => {
  it("needs a name and a value", () => {
    expect(isRowComplete(newHeaderRow())).toBe(false);
    expect(isRowComplete({ ...newHeaderRow(), name: "X-A", value: "v" })).toBe(true);
  });

  it("needs a fallback for the fallback policy", () => {
    const row = { ...newHeaderRow(), name: "X-A", value: "v", onMissing: "fallback" as const };
    expect(isRowComplete(row)).toBe(false);
    expect(isRowComplete({ ...row, fallback: "unknown" })).toBe(true);
  });
});
