import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createIndex, close } from "pagefind";
import {
  hasSwedishPages,
  languageAtLocation,
  publishedRoutes,
  sourceForPage,
  languagePath,
  localizeDocsHref,
  splitDocsPath,
  versionTargets,
} from "../src/lib/languages";
import { languagePageMap } from "../src/lib/navigation";
import type { PageMapItem } from "nextra";

const sources = new Set([
  "/",
  "/guides/deployment",
  "/guides/storage",
  "/sv",
  "/sv/guides/deployment",
]);

test("English URLs survive; Swedish falls back only within the selected ref", () => {
  assert.deepEqual(sourceForPage("/guides/deployment", sources), {
    language: "en",
    page: "/guides/deployment",
    source: "/guides/deployment",
    fallback: false,
  });
  assert.equal(sourceForPage("/sv/guides/deployment", sources).fallback, false);
  assert.deepEqual(sourceForPage("/sv/guides/storage", sources), {
    language: "sv",
    page: "/guides/storage",
    source: "/guides/storage",
    fallback: true,
  });
  const oldRef = new Set(["/", "/guides/deployment"]);
  assert.equal(sourceForPage("/sv/guides/deployment", oldRef).fallback, true);
  assert.equal(hasSwedishPages(oldRef), false);
  assert.equal(hasSwedishPages(sources), true);
  assert.deepEqual(publishedRoutes([...oldRef]), [
    "/",
    "/sv",
    "/guides/deployment",
    "/sv/guides/deployment",
  ]);
  assert.equal(
    publishedRoutes([...sources, "/sv/guides/unreleased"]).includes(
      "/sv/guides/unreleased",
    ),
    false,
  );
});

test("language URLs retain fragments and never localize assets or external links", () => {
  assert.equal(languagePath("/", "en"), "/");
  assert.equal(languagePath("/", "sv"), "/sv");
  assert.equal(languagePath("/sv?mode=1#start", "en"), "/?mode=1#start");
  assert.deepEqual(splitDocsPath("/sv"), { language: "sv", page: "/" });
  assert.equal(
    languagePath("/sv/guides/deployment", "en"),
    "/guides/deployment",
  );
  assert.equal(
    localizeDocsHref("/guides/storage?mode=1#restore", "sv"),
    "/sv/guides/storage?mode=1#restore",
  );
  for (const href of [
    "https://example.com/guides/a",
    "//example.com/a",
    "#part",
    "mailto:a@example.com",
    "/images/a.png",
    "/v2.1/guides/deployment",
  ]) {
    assert.equal(localizeDocsHref(href, "sv"), href);
  }
});

test("the site-wide 404 reads the language from any version's address", () => {
  const bases = ["", "/v2.1", "/dev"];
  for (const [pathname, language] of [
    ["/sv/guides/deployment", "sv"],
    ["/sv", "sv"],
    ["/v2.1/sv", "sv"],
    ["/dev/sv/guides/deployment", "sv"],
    ["/dev/guides/deployment", "en"],
    ["/svenska", "en"],
    ["/v2.1/guides/sv", "en"],
    ["/", "en"],
  ]) {
    assert.equal(languageAtLocation(pathname, bases), language, pathname);
  }
});

test("version switching tries the same language and page before safe roots", () => {
  assert.deepEqual(versionTargets("/v2.1", "/sv/guides/deployment"), [
    "/v2.1/sv/guides/deployment",
    "/v2.1/guides/deployment",
    "/v2.1/sv",
    "/v2.1",
  ]);
  assert.deepEqual(versionTargets("/dev", "/guides/storage"), [
    "/dev/guides/storage",
    "/dev/",
    "/dev",
  ]);
});

test("navigation reuses the ref's order and excludes the translation folder", () => {
  const map: PageMapItem[] = [
    {
      data: {
        index: { title: "Home", type: "page" },
        guides: { title: "Guides", type: "page" },
      },
    },
    { name: "index", route: "/" },
    {
      name: "guides",
      route: "/guides",
      children: [
        { data: { index: "Overview", deployment: "Deploy Eneo" } },
        {
          name: "deployment",
          route: "/guides/deployment",
          frontMatter: { title: "Deploy Eneo" },
        },
      ],
    },
    { name: "sv", route: "/sv", children: [] },
  ];
  const before = structuredClone(map);
  const result = languagePageMap(map, "sv");
  assert.deepEqual(map, before);
  assert.equal(result.length, 3);
  assert.deepEqual(result[0], {
    data: {
      index: { title: "Start", type: "page" },
      guides: { title: "Guider", type: "page" },
    },
  });
  assert.deepEqual(result[2], {
    name: "guides",
    route: "/sv/guides",
    children: [
      { data: { index: "Översikt", deployment: "Driftsätt Eneo" } },
      {
        name: "deployment",
        route: "/sv/guides/deployment",
        frontMatter: { title: "Driftsätt Eneo" },
      },
    ],
  });
});

test("Pagefind separates languages and excludes English fallback even with a nested indexed main", async () => {
  const { index, errors } = await createIndex();
  assert.deepEqual(errors, []);
  assert.ok(index);
  try {
    for (const [url, content] of [
      [
        "/guides/deployment",
        '<html lang="en"><body><main data-pagefind-body><h1>Deployment</h1>Englishsentinel</main></body></html>',
      ],
      [
        "/sv/guides/deployment",
        '<html lang="sv"><body><main data-pagefind-body><h1>Driftsättning</h1>Svenskmarkör</main></body></html>',
      ],
      [
        "/sv/guides/storage",
        '<html lang="sv"><body><nav>Navigation</nav><div data-pagefind-ignore="all"><main data-pagefind-body><aside>Översättning saknas</aside><div lang="en"><h1>Storage</h1>Fallbacksentinel</div></main></div></body></html>',
      ],
    ]) {
      const added = await index.addHTMLFile({ url, content });
      assert.deepEqual(added.errors, []);
    }
    const { files, errors: fileErrors } = await index.getFiles();
    assert.deepEqual(fileErrors, []);
    const entry = files.find((file) => file.path === "pagefind-entry.json");
    assert.ok(entry);
    const manifest = JSON.parse(new TextDecoder().decode(entry.content));
    assert.deepEqual(Object.keys(manifest.languages).sort(), ["en", "sv"]);
    assert.equal(manifest.languages.en.page_count, 1);
    assert.equal(manifest.languages.sv.page_count, 1);
  } finally {
    await index.deleteIndex();
    await close();
  }
});

test("app docs links use the reader locale and preserve English URLs and anchors", async () => {
  const { docsUrl } = await import("../../web/src/lib/core/docs");
  for (const page of [
    "guides/object-content-storage",
    "guides/embed-widget",
  ] as const) {
    assert.equal(docsUrl(page, "en"), `https://docs.eneo.ai/${page}`);
    assert.equal(docsUrl(page, "sv"), `https://docs.eneo.ai/sv/${page}`);
    assert.equal(
      docsUrl(page, "sv", "installation"),
      `https://docs.eneo.ai/sv/${page}#installation`,
    );
  }
});

test("translated MDX and historical JSX links compile through the language adapters", async () => {
  const { compileMdx } = await import("nextra/compile");
  const { readFileSync, readdirSync } = await import("node:fs");
  const { default: localizeMdxLinks } =
    await import("./localize-mdx-links.mjs");
  const compiled = await compileMdx(
    '<a href="/guides/deployment">Deploy</a>\n\n<Cards.Card title="Deploy" href="/guides/deployment" />',
    {
      mdxOptions: { remarkPlugins: [localizeMdxLinks] },
    },
  );
  assert.match(compiled, /DocsLink/);
  assert.match(compiled, /DocsCard/);
  const widget = readFileSync(
    new URL("../src/content/sv/guides/embed-widget.mdx", import.meta.url),
    "utf8",
  );
  assert.match(await compileMdx(widget), /id: "for-the-website-team"/);
  const translations = new URL("../src/content/sv/", import.meta.url);
  for (const file of readdirSync(translations, { recursive: true }).filter(
    (file) => file.toString().endsWith(".mdx"),
  )) {
    await compileMdx(
      readFileSync(new URL(file.toString(), translations), "utf8"),
      { staticImage: false, mdxOptions: { remarkPlugins: [localizeMdxLinks] } },
    );
  }
});

// Commands inside fenced code blocks; prose that merely mentions one is ignored.
function shellCommands(mdx: string): string[] {
  const commands: string[] = [];
  let fenced = false;
  for (const line of mdx.split("\n")) {
    if (/^\s*```/.test(line)) fenced = !fenced;
    else if (fenced) commands.push(line.trim());
  }
  return commands;
}

test("installation guides create the external network before any compose command needs it", () => {
  for (const guide of ["guides/deployment.mdx", "sv/guides/deployment.mdx"]) {
    const commands = shellCommands(
      readFileSync(new URL(`../src/content/${guide}`, import.meta.url), "utf8"),
    );
    const network = commands.indexOf("docker network create proxy_tier");
    const compose = commands.findIndex((command) =>
      /^docker compose (run|up|create|start)\b/.test(command),
    );
    assert.ok(network >= 0 && compose >= 0, guide);
    assert.ok(
      network < compose,
      `${guide}: "${commands[compose]}" joins the external network before it is created`,
    );
  }
});
