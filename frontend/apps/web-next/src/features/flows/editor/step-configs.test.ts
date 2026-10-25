import { describe, expect, it } from "vitest";
import {
  argumentValue,
  longMaterialEligibility,
  newSourceRef,
  readHttpConfig,
  readInputBindings,
  readLongMaterial,
  readRuntimeInput,
  readTemplateFill,
  toolArguments,
  withHttpConfig,
  withLongMaterial,
  withReviewChoice,
  withRuntimeInput,
  withTemplate,
  withToolConfig,
  writeInputBindings
} from "./step-configs";

describe("underlag", () => {
  it("keeps what a chosen result stores beyond what the editor shows", () => {
    const stored = {
      question: "Jämför",
      source_refs: [
        { step_ref: "step_1", output: "text", label: "Ansökan", item_template: "{{item}}" }
      ]
    };
    const state = readInputBindings(stored);
    if (state.status !== "valid") throw new Error("expected valid bindings");
    const next = writeInputBindings(state.question, [
      ...state.sourceRefs,
      newSourceRef(2, "structured", "beslut")
    ]);
    expect(next).toEqual({
      question: "Jämför",
      source_refs: [
        { step_ref: "step_1", output: "text", label: "Ansökan", item_template: "{{item}}" },
        { step_ref: "step_2", output: "structured", field_path: "beslut" }
      ]
    });
    expect(writeInputBindings("  ", [])).toBeNull();
  });

  it("leaves bindings with keys it does not know alone", () => {
    expect(readInputBindings({ question: "x", unknown: 1 }).status).toBe("unsupported");
  });
});

describe("uploads", () => {
  it("turning uploads off keeps their stored settings for later", () => {
    const stored = {
      runtime_input: {
        enabled: true,
        required: true,
        label: "Ansökan",
        execution_mode: "per_source"
      }
    };
    const next = withRuntimeInput(stored, "document", { enabled: false });
    expect(next.runtime_input).toEqual({
      enabled: false,
      required: true,
      label: "Ansökan",
      execution_mode: "per_source",
      input_format: "document"
    });
    expect(readRuntimeInput(next)).toMatchObject({ enabled: false, label: "Ansökan" });
  });
});

describe("HTTP", () => {
  it("round-trips a stored secret as its sentinel and never as a value", () => {
    const stored = {
      url: "https://api.example.org",
      auth: { mode: "bearer_token", token: { $secret: "stored" } },
      timeout_seconds: 20,
      body: { mode: "none" },
      custom_headers: [{ name: "X-Key", value: { $secret: "stored" }, secret: true }],
      response_format: "json",
      text_processing: { mode: "summarize" }
    };
    const config = readHttpConfig(stored, "input");
    expect(config.auth).toEqual({ mode: "bearer_token", token: { $secret: "stored" } });
    expect(withHttpConfig(stored, config)).toEqual(stored);
  });
});

describe("tools", () => {
  it("writes the three keys of a tool and keeps the step's other input settings", () => {
    expect(
      withToolConfig(
        { text_processing: { mode: "summarize" } },
        { mcp_server_id: "s1", tool_id: "t1", arguments: { q: "{{flow_input.namn}}" } }
      )
    ).toEqual({
      text_processing: { mode: "summarize" },
      tool: { mcp_server_id: "s1", tool_id: "t1", arguments: { q: "{{flow_input.namn}}" } }
    });
  });

  it("reads an argument's text as its schema type, a reference always as text", () => {
    expect(argumentValue("5", "integer")).toEqual({ ok: true, value: 5 });
    expect(argumentValue("{{step_1.output.structured.antal}}", "integer")).toEqual({
      ok: true,
      value: "{{step_1.output.structured.antal}}"
    });
    expect(argumentValue("fem", "integer")).toEqual({ ok: false });
    expect(argumentValue("", "string")).toEqual({ ok: true, value: undefined });
  });
});

describe("toolArguments", () => {
  it("keeps what the approved schema says about an argument, for information", () => {
    const [list, limit, day, plain] = toolArguments({
      required: ["list"],
      properties: {
        limit: { type: "integer", minimum: 1, maximum: 50, default: 10 },
        day: { type: "string", format: "date" },
        list: { type: "array", items: { type: "string" } },
        plain: { type: "string", description: "Fri text" }
      }
    });
    expect(list).toMatchObject({ name: "list", required: true, type: "array", items: "string" });
    expect(limit).toMatchObject({ minimum: 1, maximum: 50, default: 10 });
    expect(day).toMatchObject({ format: "date" });
    expect(plain).toMatchObject({
      description: "Fri text",
      items: null,
      format: null,
      minimum: null,
      maximum: null,
      default: undefined
    });
  });
});

describe("templates", () => {
  it("keeps the bindings of placeholders the new template still has", () => {
    const stored = {
      template_asset_id: "a1",
      template_checksum: "abc",
      placeholders: ["namn", "datum"],
      bindings: { namn: "{{flow_input.namn}}", datum: "{{datum}}" },
      future: 1
    };
    const next = withTemplate(stored, {
      assetId: "a2",
      name: "Beslut.docx",
      placeholders: ["namn"]
    });
    expect(next).toEqual({
      template_asset_id: "a2",
      template_name: "Beslut.docx",
      placeholders: ["namn"],
      bindings: { namn: "{{flow_input.namn}}" },
      future: 1
    });
    expect(readTemplateFill(next).templateAssetId).toBe("a2");
  });
});

describe("review", () => {
  it("keeps the stored expiry when only the mode changes", () => {
    expect(withReviewChoice({ mode: "view", expires_after_seconds: 7200 }, "edit")).toEqual({
      mode: "edit",
      expires_after_seconds: 7200
    });
    expect(withReviewChoice({ mode: "view" }, "none")).toBeNull();
  });
});

describe("long material", () => {
  it("is set and cleared without touching the step's other input settings", () => {
    const stored = { runtime_input: { enabled: true, input_format: "document" } };
    const on = withLongMaterial(stored, true);
    expect(on).toEqual({ ...stored, long_material: { mode: "digest" } });
    expect(readLongMaterial(on)).toBe(true);
    expect(withLongMaterial(on, false)).toEqual(stored);
    expect(withLongMaterial({ long_material: { mode: "digest" } }, false)).toBeNull();
  });

  it("is offered only on a completion step that reads its material whole", () => {
    expect(longMaterialEligibility({ output_mode: "pass_through", input_config: null })).toBe(
      "eligible"
    );
    expect(longMaterialEligibility({ output_mode: "http_post", input_config: null })).toBe(
      "eligible"
    );
    expect(longMaterialEligibility({ output_mode: "compose_text", input_config: null })).toBe(
      "output"
    );
    expect(
      longMaterialEligibility({
        output_mode: "pass_through",
        input_config: { text_processing: { mode: "summarize" } }
      })
    ).toBe("text_processing");
    expect(
      longMaterialEligibility({
        output_mode: "pass_through",
        input_config: { item_map: { enabled: true } }
      })
    ).toBe("mapped");
    expect(
      longMaterialEligibility({
        output_mode: "pass_through",
        input_config: { runtime_input: { enabled: true, execution_mode: "per_source" } }
      })
    ).toBe("mapped");
  });
});
