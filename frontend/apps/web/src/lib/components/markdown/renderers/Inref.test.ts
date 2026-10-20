import type { InfoBlob } from "@eneo/eneo-js";
import { render } from "svelte/server";
import { expect, it } from "vitest";
import { Markdown } from "$lib/components/markdown/index";

function reference(id: string, url: string | null): InfoBlob {
  return { id, metadata: { url, title: "Riktlinje" } } as unknown as InfoBlob;
}

it("links a citation to a stored http(s) address", () => {
  const { body } = render(Markdown, {
    props: {
      source: 'Se <inref id="aaaaaaaa"/>',
      references: [reference("aaaaaaaa-1", "https://kommun.se/riktlinje")]
    }
  });

  expect(body).toContain('href="https://kommun.se/riktlinje"');
});

it.each([
  "javascript:alert(document.cookie)",
  "java\tscript:alert(1)",
  "data:text/html,x",
  "mailto:registrator@kommun.se",
  "/spaces/1/settings",
  "https:/spaces/1/settings",
  "https:settings",
  "ht tps://kommun.se/riktlinje",
  "https://"
])("renders a citation to %j without a link", (url) => {
  const { body } = render(Markdown, {
    props: { source: 'Se <inref id="aaaaaaaa"/>', references: [reference("aaaaaaaa-1", url)] }
  });

  expect(body).toMatch(/<a\b[^>]*>1<\/a>/);
  expect(body).not.toContain("href=");
  expect(body.toLowerCase()).not.toContain("script:");
});
