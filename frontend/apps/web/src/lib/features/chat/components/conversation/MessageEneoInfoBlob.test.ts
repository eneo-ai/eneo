import type { InfoBlob } from "@eneo/eneo-js";
import { render } from "svelte/server";
import { expect, it, vi } from "vitest";
import { Markdown } from "$lib/components/markdown/index";
import MessageEneoInfoBlob from "./MessageEneoInfoBlob.svelte";

const message = vi.hoisted(() => ({ references: [] as unknown[] }));

vi.mock("../../MessageContext.svelte", () => ({
  getMessageContext: () => ({
    current: () => ({ references: message.references, mcp_tool_references: [], answer: "" })
  })
}));
vi.mock("$lib/features/knowledge/FaviconUrlService.svelte", () => ({
  getFaviconUrlService: () => ({ getFavicon: () => "" })
}));

function reference(url: string | null): InfoBlob {
  return {
    id: "aaaaaaaa-1",
    metadata: { url, title: "Riktlinje" },
    source_metadata: []
  } as unknown as InfoBlob;
}

function citation(url: string | null): string {
  message.references = [reference(url)];
  return render(Markdown, {
    props: {
      source: 'Se <inref id="aaaaaaaa"/>',
      references: message.references as InfoBlob[],
      customRenderers: { inref: MessageEneoInfoBlob }
    }
  }).body;
}

it("links a citation to a stored http(s) address", () => {
  expect(citation("https://kommun.se/riktlinje")).toContain('href="https://kommun.se/riktlinje"');
});

it.each([
  "javascript:alert(document.cookie)",
  "JaVaScRiPt:alert(1)",
  "vbscript:msgbox(1)",
  "mailto:registrator@kommun.se",
  "//annan.example/sida",
  "https:/spaces/1/settings",
  "https:settings",
  "ht tps://kommun.se/riktlinje",
  "https://"
])("previews a citation to %j instead of linking it", (url) => {
  const body = citation(url);

  expect(body).not.toMatch(/<a\b/);
  expect(body).toContain('type="button"');
  expect(body.toLowerCase()).not.toContain("script:");
});
