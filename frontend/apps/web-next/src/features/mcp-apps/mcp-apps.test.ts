import { describe, expect, it } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { appViewTitle, hasResult, messageAppViewCalls, parseAppView } from "./mcp-apps";

type Part = EneoUIMessage["parts"][number];

const view = { view_id: "view-1", mcp_server_id: "server-1", ui: { prefersBorder: true } };

function answer(
  calls: {
    id: string;
    toolName: string;
    input?: Record<string, unknown>;
    state?: "input-streaming" | "input-available" | "output-available" | "output-error";
    isBundled?: boolean;
    appView?: Record<string, unknown> | null;
    approved?: boolean | null;
    errorText?: string;
  }[]
): EneoUIMessage {
  return {
    id: "answer",
    role: "assistant",
    parts: calls.map(
      (call) =>
        ({
          type: "dynamic-tool",
          toolName: call.toolName,
          toolCallId: call.id,
          state: call.state ?? "output-available",
          input: call.input ?? {},
          output: { status: "succeeded" },
          errorText: call.errorText,
          callProviderMetadata: {
            eneo: {
              server_name: "runtime",
              is_bundled: call.isBundled ?? true,
              app_view: call.appView === undefined ? view : call.appView,
              approved: call.approved ?? null
            }
          }
        }) as unknown as Part
    )
  };
}

const t = (key: string) => key;

describe("view-bearing calls", () => {
  it("shows a call whose tool has a view, from the moment it is announced", () => {
    const calls = messageAppViewCalls(
      answer([
        { id: "c1", toolName: "query_table", state: "input-streaming", input: { sql: "SEL" } }
      ])
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]!.view).toEqual({ viewId: "view-1", ui: { prefersBorder: true } });
    expect(calls[0]!.input).toEqual({ sql: "SEL" });
  });

  it("leaves out calls without a view, refused calls and failed calls", () => {
    const calls = messageAppViewCalls(
      answer([
        { id: "none", toolName: "query_table", appView: null },
        { id: "bad", toolName: "query_table", appView: { ui: {} } },
        { id: "refused", toolName: "query_table", approved: false },
        { id: "failed", toolName: "query_table", state: "output-error", errorText: "failed" },
        { id: "ok", toolName: "query_table" }
      ])
    );
    expect(calls.map((call) => call.toolCallId)).toEqual(["ok"]);
  });

  it("keeps document-only chart exports and image exports out of the inline views", () => {
    const calls = messageAppViewCalls(
      answer([
        { id: "report", toolName: "create_chart", input: { display: "none" } },
        { id: "png", toolName: "create_chart", input: { format: "png" } },
        { id: "svg", toolName: "create_chart", input: { include_svg: true } },
        { id: "shown", toolName: "create_chart", input: { title: "Ärenden" } },
        { id: "external", toolName: "create_chart", input: { format: "png" }, isBundled: false }
      ])
    );
    expect(calls.map((call) => call.toolCallId)).toEqual(["shown", "external"]);
  });

  it("titles Eneo's own views in the reader's language and external ones by their tool", () => {
    const [table, external] = messageAppViewCalls(
      answer([
        { id: "t", toolName: "query_table" },
        { id: "e", toolName: "map_view", isBundled: false }
      ])
    );
    expect(appViewTitle(table, t)).toBe("mcp_app_table_title");
    expect(appViewTitle(external, t)).toBe("map_view");
  });

  it("hands the result to the view once the answer is stored", () => {
    const [call] = messageAppViewCalls(answer([{ id: "c", toolName: "query_table" }]));
    expect(hasResult(call!, true)).toBe(false);
    expect(hasResult(call!, false)).toBe(true);
    expect(hasResult({ resultStatus: "pending", state: "input-available" }, false)).toBe(false);
  });

  it("parses a view defensively", () => {
    expect(parseAppView({ view_id: "v", ui: null })).toEqual({ viewId: "v", ui: {} });
    expect(parseAppView({ view_id: "" })).toBeNull();
    expect(parseAppView("v")).toBeNull();
  });
});
