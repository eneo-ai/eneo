/**
 * Emits the machine-readable mirror of the documentation site.
 *
 * The exported `out/*.txt` files Next.js writes are React server-component
 * payloads, not prose, so an agent that fetches them learns nothing. This step
 * writes, next to every exported page, the Markdown a language model can read
 * directly, plus the two index files agents look for by convention:
 *
 *   out/<route>.md   the page body, JSX flattened to Markdown
 *   out/llms.txt     an index: one line per page, with its .md link
 *   out/llms-full.txt  every page concatenated, for a single fetch
 *
 * Run it after `next build` and before Pagefind indexes `out/`.
 */
import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const appDir = dirname(dirname(fileURLToPath(import.meta.url)));
const contentDir = join(appDir, "src", "content");
const outDir = join(appDir, "out");
const siteUrl = "https://docs.eneo.ai";

// Reading order for the Flows-only bundle: product, API guide, developer pages,
// then the Builder. Routes not listed here are excluded from llms-flows.txt.
export const FLOWS_BUNDLE_ROUTES = [
  "docs/flows",
  "guides/flows",
  "guides/flows/designing-flows",
  "guides/flows/integrating-flows",
  "guides/flows/agent-skill",
  "guides/flows-api-guide",
  "guides/flows/reference/errors",
  "guides/flows/flows-faq",
  "docs/flows-for-developers",
  "docs/flows-for-developers/how-built",
  "docs/flows-for-developers/data-schema",
  "docs/flows-for-developers/run-lifecycle",
  "docs/flows-for-developers/when-things-fail",
  "docs/flows-for-developers/key-decisions",
  "docs/flows-for-developers/reviewing-flows-code",
  "docs/ai-builder",
];

const SECTION_TITLES = {
  docs: "Documentation",
  guides: "Guides",
  about: "About",
  contributing: "Contributing",
  "": "Overview",
};

async function collectMdxFiles(dir) {
  const found = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...(await collectMdxFiles(full)));
    else if (entry.name.endsWith(".mdx")) found.push(full);
  }
  return found;
}

/** Split YAML frontmatter from the page body. */
function splitFrontmatter(source) {
  const match = source.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!match) return { frontmatter: {}, body: source };
  const frontmatter = {};
  for (const line of match[1].split("\n")) {
    const pair = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (pair) frontmatter[pair[1]] = pair[2].replace(/^["']|["']$/g, "").trim();
  }
  return { frontmatter, body: source.slice(match[0].length) };
}

/**
 * Turn MDX prose into Markdown a model can read without a JSX runtime.
 *
 * Fenced code blocks are copied through untouched. The pages publish complete
 * client examples whose own `import` and `export` lines look exactly like the
 * MDX component imports this strips, so rewriting inside a fence would silently
 * mutilate the very examples this output exists to expose.
 */
export function flattenMdx(source) {
  const out = [];
  let insideFence = false;
  for (const line of source.split("\n")) {
    if (/^\s*(```|~~~)/.test(line)) {
      insideFence = !insideFence;
      out.push(line);
      continue;
    }
    if (insideFence) {
      out.push(line);
      continue;
    }
    if (/^(import|export)\b/.test(line)) continue;
    out.push(
      line
        .replace(/<Callout[^>]*>/g, "> **Note**\n>")
        .replace(/<\/Callout>/g, "")
        .replace(/<\/?(Tabs|Tabs\.Tab|Cards|Cards\.Card|Steps)[^>]*>/g, "")
        .replace(/<[A-Z][A-Za-z]*\s*\/>/g, ""),
    );
  }
  return out
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function routeFor(file) {
  const rel = relative(contentDir, file).replace(/\\/g, "/");
  const route = rel.replace(/\.mdx$/, "").replace(/(^|\/)index$/, "");
  return route;
}

function titleFor(frontmatter, body, route) {
  if (frontmatter.title) return frontmatter.title;
  const heading = body.match(/^#\s+(.+)$/m);
  if (heading) return heading[1].trim();
  return route || "Overview";
}

function summaryFor(body) {
  const afterHeading = body.replace(/^#\s+.+$/m, "");
  for (const block of afterHeading.split("\n\n")) {
    const line = block.trim();
    if (!line || line.startsWith("#") || line.startsWith("|")) continue;
    if (line.startsWith("```") || line.startsWith(">") || line.startsWith("<"))
      continue;
    return line.replace(/\s+/g, " ").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  }
  return "";
}

export async function buildLlmText() {
  const pages = [];
  for (const file of (await collectMdxFiles(contentDir)).sort()) {
    const { frontmatter, body: raw } = splitFrontmatter(
      await readFile(file, "utf8"),
    );
    const flattened = flattenMdx(raw);
    const route = routeFor(file);
    const title = titleFor(frontmatter, flattened, route);
    const body = /^#\s+/m.test(flattened)
      ? flattened
      : `# ${title}\n\n${flattened}`;
    const mdPath = join(outDir, `${route || "index"}.md`);
    await mkdir(dirname(mdPath), { recursive: true });
    await writeFile(mdPath, `${body}\n`, "utf8");
    pages.push({
      route,
      title,
      summary: summaryFor(body),
      body,
      href: `/${route || "index"}.md`,
    });
  }

  const bySection = new Map();
  for (const page of pages) {
    const section = page.route.includes("/")
      ? page.route.split("/")[0]
      : page.route === ""
        ? ""
        : page.route;
    const key = SECTION_TITLES[section] ? section : page.route.split("/")[0];
    const list = bySection.get(key) ?? [];
    list.push(page);
    bySection.set(key, list);
  }

  const indexLines = [
    "# Eneo",
    "",
    "> Eneo is an open-source AI platform for the Swedish public sector. Eneo Flows is its",
    "> workflow runtime: a published flow runs as a sequence of steps, can pause for human",
    "> review, and returns typed results and downloadable artifacts over an HTTP API.",
    "",
    "Every page below is available as Markdown at the linked path. The complete site is also",
    "available as a single document at /llms-full.txt; the Flows pages alone (product guide,",
    "API guide, developer pages, AI Builder) are at /llms-flows.txt. The runtime API contract",
    "is served as OpenAPI 3.1 from the Eneo deployment itself at /openapi.json.",
    "",
  ];
  for (const [section, list] of bySection) {
    indexLines.push(`## ${SECTION_TITLES[section] ?? section}`, "");
    for (const page of list.sort((a, b) => a.route.localeCompare(b.route))) {
      indexLines.push(
        `- [${page.title}](${siteUrl}${page.href})${page.summary ? `: ${page.summary}` : ""}`,
      );
    }
    indexLines.push("");
  }
  await writeFile(
    join(outDir, "llms.txt"),
    `${indexLines.join("\n").trim()}\n`,
    "utf8",
  );

  const fullParts = pages
    .sort((a, b) => a.route.localeCompare(b.route))
    .map((page) => `<!-- source: ${page.href} -->\n\n${page.body}`);
  await writeFile(
    join(outDir, "llms-full.txt"),
    `${["# Eneo documentation (complete)", "", ...fullParts].join("\n\n---\n\n")}\n`,
    "utf8",
  );

  const byRoute = new Map(pages.map((page) => [page.route, page]));
  const missing = FLOWS_BUNDLE_ROUTES.filter((route) => !byRoute.has(route));
  if (missing.length) {
    throw new Error(
      `llms-flows.txt lists routes that do not exist: ${missing.join(", ")}`,
    );
  }
  const flowsParts = FLOWS_BUNDLE_ROUTES.map((route) => byRoute.get(route)).map(
    (page) => `<!-- source: ${page.href} -->\n\n${page.body}`,
  );
  await writeFile(
    join(outDir, "llms-flows.txt"),
    `${[
      "# Eneo Flows documentation",
      "",
      "Product guide, API guide, developer pages, and AI Builder, in reading order. Each part",
      "names its source page; the same pages are listed in /llms.txt.",
      ...flowsParts,
    ].join("\n\n---\n\n")}\n`,
    "utf8",
  );

  return pages;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const pages = await buildLlmText();
  console.log(
    `llm text: wrote ${pages.length} .md pages, llms.txt, llms-full.txt and llms-flows.txt`,
  );
}
