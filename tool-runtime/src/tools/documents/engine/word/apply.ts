// Runs inside sandbox children only. Puts content into a Word template through the docx
// library's patcher: the template keeps its styles, numbering, headers, footers, page setup
// and relationships, and the content is written in its styles. Two conventions are served,
// content controls and {{placeholders}} (see inspect.ts); a control is reduced to a
// placeholder of its own before the one patch call (controls.ts), and list definitions are
// added to the numbering part first (numbering.ts).
import { PatchType, TextRun, patchDocument, type IPatch } from "docx";
import { ToolError } from "../../../../errors";
import { parseMarkdown, type Block } from "../../markdown/parse";
import type { DocumentSpec } from "../../ports";
import { listNeeds, renderBlocks, titleParagraph } from "../docx";
import type { DocumentImages } from "../images";
import { placeToken, placeValue, removeControl, replaceBody } from "./controls";
import {
  controlsOf,
  headerFooterParts,
  inspectTemplate,
  openWordTemplate,
  parsedPart,
  readStyles,
  type Placeholder,
  type PlaceholderLocation,
  type TemplateInspection,
  type Zip,
} from "./inspect";
import { ensureListDefinitions, type ListIds, type ListNeeds } from "./numbering";
import { element, find, rootElement, serializeXml, textNode, type Element } from "./ooxml";

type MarkdownDocument = Extract<DocumentSpec, { kind: "markdown" }>;
/** A value for one placeholder: text, or Markdown for a rich control. */
export type Fill = { placeholder: Placeholder; value: string };
export type Filled = { buffer: Buffer; placeholders: string[] };

/** Names the template may use for values a document carries itself. */
const AUTO_VALUES: Record<string, (document: MarkdownDocument, organisation: string) => string> = {
  title: (document) => document.title,
  titel: (document) => document.title,
  rubrik: (document) => document.title,
  date: () => new Date().toISOString().slice(0, 10),
  datum: () => new Date().toISOString().slice(0, 10),
  year: () => String(new Date().getFullYear()),
  år: () => String(new Date().getFullYear()),
  organisation: (_, organisation) => organisation,
  organization: (_, organisation) => organisation,
  organisationen: (_, organisation) => organisation,
  author: (_, organisation) => organisation,
  författare: (_, organisation) => organisation,
  forfattare: (_, organisation) => organisation,
};

function describe(placeholder: Placeholder): string {
  const kind = placeholder.kind === "rich" ? "a document in Markdown" : "text";
  const label = placeholder.label ? ` "${placeholder.label}"` : "";
  const hint = placeholder.hint ? `: ${placeholder.hint}` : "";
  return `${placeholder.name}${label} (${kind})${hint}`;
}

/** The placeholders a caller can fill, each name once. */
export function fillable(inspection: TemplateInspection): Placeholder[] {
  const seen = new Set<string>();
  return inspection.placeholders.filter((placeholder) => {
    if (!placeholder.supported || seen.has(placeholder.name)) return false;
    seen.add(placeholder.name);
    return true;
  });
}

/** Refuses when a fillable placeholder has no value, naming them all so one retry suffices. */
function requireValues(placeholders: Placeholder[], values: Map<string, string>): void {
  const missing = placeholders.filter((placeholder) => !values.has(placeholder.name));
  if (!missing.length) return;
  throw new ToolError(
    "TEMPLATE_VALUES_MISSING",
    `The template has these placeholders: ${placeholders.map(describe).join("; ")}. No value was given for: ${missing
      .map((placeholder) => placeholder.name)
      .join(
        ", ",
      )}. Pass a value for each, named exactly as listed; an empty string leaves a {{placeholder}} blank and removes a content control. Ask the user for a value you do not know.`,
  );
}

type Part = { name: string; root: Element; location: PlaceholderLocation };

async function parts(zip: Zip): Promise<Part[]> {
  const result: Part[] = [
    {
      name: "word/document.xml",
      root: (await parsedPart(zip, "word/document.xml"))!,
      location: "body",
    },
  ];
  for (const { name, location } of headerFooterParts(zip)) {
    const root = await parsedPart(zip, name);
    if (root) result.push({ name, root, location });
  }
  return result;
}

type RichPatch = { token: string; blocks: Block[]; headingShift: number; lead?: boolean };

/**
 * Applies fills to the template. Text goes to {{placeholders}} and text controls; Markdown
 * goes to rich controls; `body`, when given, replaces the template's whole body.
 */
async function patchTemplate(
  zip: Zip,
  inspection: TemplateInspection,
  fills: Fill[],
  options: {
    images: DocumentImages;
    organisationName?: string;
    title?: string;
    language?: string;
    body?: Block[];
    lead?: boolean;
  },
): Promise<Buffer> {
  const patches: Record<string, IPatch> = {};
  const rich: RichPatch[] = [];
  let tokens = 0;
  const token = () => `eneo:${tokens++}`;
  const textPatch = (value: string): IPatch => ({
    type: PatchType.PARAGRAPH,
    children: value
      .split(/\r?\n/)
      .map((line, index) => new TextRun({ text: line, break: index > 0 ? 1 : undefined })),
  });
  const styles = readStyles(await parsedPart(zip, "word/styles.xml"));
  const documentParts = await parts(zip);
  for (const part of documentParts) {
    const controls = controlsOf(part.root, part.location, styles.headingLevelOf);
    for (const fill of fills) {
      if (fill.placeholder.syntax !== "control" || fill.placeholder.location !== part.location)
        continue;
      for (const { placeholder, sdt } of controls) {
        if (placeholder.name !== fill.placeholder.name || !placeholder.supported) continue;
        if (fill.value === "") {
          removeControl(part.root, sdt);
          continue;
        }
        if (placeholder.kind !== "rich") {
          placeValue(sdt, fill.value);
          continue;
        }
        const name = token();
        placeToken(sdt, name);
        rich.push({
          token: name,
          blocks: parseMarkdown(fill.value),
          headingShift: placeholder.headingLevel,
          ...(fill.placeholder === inspection.contentPlaceholder ? { lead: options.lead } : {}),
        });
      }
    }
    if (options.body && part.location === "body") {
      const name = token();
      replaceBody(rootElement(part.root), name);
      rich.push({ token: name, blocks: options.body, headingShift: 0, lead: options.lead });
    }
    zip.file(part.name, serializeXml(part.root));
  }
  for (const fill of fills) {
    if (fill.placeholder.syntax !== "braces") continue;
    const key = fill.placeholder.written!;
    if (fill.placeholder.name === "content" && options.title !== undefined && !options.body) {
      // The content placeholder takes the whole document, not a value.
      rich.push({
        token: key,
        blocks: parseMarkdown(fill.value),
        headingShift: 0,
        lead: options.lead,
      });
      continue;
    }
    patches[key] = textPatch(fill.value);
  }
  // Every rich patch draws its list definitions from one pass over the numbering part.
  const needs: ListNeeds = { bullets: false, numbered: [] };
  const perPatch = rich.map((patch) => {
    const need = listNeeds(patch.blocks);
    needs.bullets ||= need.bullets;
    needs.numbered.push(...need.numbered);
    return need;
  });
  const ids = await ensureListDefinitions(zip, inspection, needs);
  let taken = 0;
  rich.forEach((patch, index) => {
    const own: ListIds = {
      bullet: ids.bullet,
      numbered: ids.numbered.slice(taken, taken + perPatch[index]!.numbered.length),
    };
    taken += perPatch[index]!.numbered.length;
    const children = renderBlocks(patch.blocks, {
      images: options.images,
      page: inspection.page,
      styles: inspection.styles,
      lists: own,
      headingShift: patch.headingShift,
    });
    patches[patch.token] = {
      type: PatchType.DOCUMENT,
      children:
        patch.lead && options.title !== undefined
          ? [titleParagraph(options.title, inspection.styles), ...children]
          : children,
    };
  });
  let buffer = Buffer.from(await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
  if (Object.keys(patches).length)
    buffer = Buffer.from(
      await patchDocument({
        outputType: "nodebuffer",
        data: buffer,
        patches,
        keepOriginalStyles: true,
      }),
    );
  return setCoreProperties(buffer, {
    title: options.title,
    language: options.language,
    creator: options.organisationName,
  });
}

/** Sets the document properties readers and accessibility checkers look at. */
async function setCoreProperties(
  buffer: Buffer,
  properties: { title?: string; language?: string; creator?: string },
): Promise<Buffer> {
  const JSZip = (await import("jszip")).default;
  const zip = await JSZip.loadAsync(buffer);
  const core = await parsedPart(zip, "docProps/core.xml");
  if (!core) return buffer;
  const root = rootElement(core);
  const set = (name: string, value: string | undefined) => {
    if (value === undefined) return;
    const existing = find(root, name);
    const node = existing ?? element(name);
    node.elements = [textNode(value)];
    if (!existing) (root.elements ??= []).push(node);
  };
  set("dc:title", properties.title);
  set("dc:language", properties.language);
  set("dc:creator", properties.creator);
  zip.file("docProps/core.xml", serializeXml(core));
  return Buffer.from(await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

/**
 * Renders a Markdown document into a Word template. The document goes where the template
 * says (a rich content control with a content tag, a {{content}} paragraph, or the whole
 * body); the template's other placeholders take the document's own values (title, date,
 * organisation) and `fields`, which must then cover the rest.
 */
export async function renderIntoTemplate(
  template: Buffer,
  document: MarkdownDocument,
  options: { images: DocumentImages; organisationName?: string },
): Promise<Buffer> {
  const zip = await openWordTemplate(template);
  const inspection = await inspectTemplate(zip);
  const organisation = options.organisationName ?? "Eneo";
  const blocks = parseMarkdown(document.content);
  const startsWithTitle = blocks[0]?.type === "heading" && blocks[0].level === 1;
  const others = fillable(inspection).filter(
    (placeholder) => placeholder !== inspection.contentPlaceholder && placeholder.kind !== "rich",
  );
  const values = new Map<string, string>();
  for (const placeholder of others) {
    const auto = AUTO_VALUES[placeholder.name.toLowerCase()];
    if (auto) values.set(placeholder.name, auto(document, organisation));
  }
  for (const [name, value] of Object.entries(document.fields ?? {})) values.set(name.trim(), value);
  if (document.fields) requireValues(others, values);
  const fills: Fill[] = others
    .filter((placeholder) => values.has(placeholder.name))
    .map((placeholder) => ({ placeholder, value: values.get(placeholder.name)! }));
  // A title placeholder in the body shows the title (one in a header or footer is a running
  // title); otherwise it leads the content unless the content starts with a level-1 heading.
  const titled = others.some(
    (placeholder) =>
      placeholder.location === "body" &&
      ["title", "titel", "rubrik"].includes(placeholder.name.toLowerCase()),
  );
  const lead = !titled && !startsWithTitle;
  const content = inspection.contentPlaceholder;
  if (content) fills.push({ placeholder: content, value: document.content });
  return patchTemplate(zip, inspection, fills, {
    images: options.images,
    organisationName: organisation,
    title: document.title,
    language: inspection.language ?? (document.language === "sv" ? "sv-SE" : "en-GB"),
    ...(content ? {} : { body: blocks }),
    lead,
  });
}

/** Fills a Word template: every fillable placeholder needs a value. */
export async function fillTemplateDocx(
  template: Buffer,
  values: Record<string, string>,
): Promise<Filled> {
  const zip = await openWordTemplate(template);
  const inspection = await inspectTemplate(zip);
  const placeholders = fillable(inspection);
  if (!placeholders.length) return { buffer: template, placeholders: [] };
  const given = new Map(Object.entries(values).map(([name, value]) => [name.trim(), value]));
  requireValues(placeholders, given);
  const buffer = await patchTemplate(
    zip,
    inspection,
    placeholders.map((placeholder) => ({ placeholder, value: given.get(placeholder.name)! })),
    { images: new Map() },
  );
  return { buffer, placeholders: placeholders.map((placeholder) => placeholder.name) };
}
