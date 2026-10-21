// Runs inside sandbox children only. Reads what a Word template offers: the styles content
// should be written in (resolved by style name, since Word localises style ids: a Swedish
// template has `Rubrik1` for "heading 1"), the list definitions its list styles use, and the
// places content can go. Two conventions are read: content controls (a `w:sdt` with a tag;
// a block-level rich control takes a document, a text control one value) and `{{name}}`
// placeholders. Nothing is changed here; the checks feed the administrator's upload view.
import { patchDetector } from "docx";
import { assertZipWithinBounds } from "../../../tabular/zip-guard";
import type { TemplateReport } from "../../ports";
import {
  at,
  attr,
  children,
  find,
  findAll,
  parseXml,
  rootElement,
  textOf,
  walk,
  type Element,
} from "./ooxml";

export class TemplateError extends Error {}

export type Zip = Awaited<ReturnType<(typeof import("jszip"))["loadAsync"]>>;
const MAX_EXPANDED_BYTES = 64 * 1024 * 1024;
const BRACES = /\{\{(.+?)\}\}/g;
/** Tags of a rich control that takes the whole document (Flows' standard templates use `dokument`). */
const CONTENT_TAGS = new Set(["content", "dokument", "innehåll", "innehall", "body"]);
/** Control types that are not text or rich text, by the element that marks them in `w:sdtPr`. */
const OTHER_CONTROL_TYPES = new Set([
  "w:date",
  "w:comboBox",
  "w:dropDownList",
  "w:picture",
  "w:docPartObj",
  "w:docPartList",
  "w:group",
  "w:citation",
  "w:bibliography",
  "w:equation",
  "w14:checkbox",
  "w15:repeatingSection",
  "w15:repeatingSectionItem",
]);

export type PlaceholderKind = "rich" | "text";
export type PlaceholderLocation = "body" | "header" | "footer";
export type Placeholder = {
  /** The control's tag, or the trimmed name between the braces. */
  name: string;
  syntax: "control" | "braces";
  /** A rich control takes a document in Markdown; a text control or a braces placeholder one value. */
  kind: PlaceholderKind;
  /** The text between the braces exactly as written (the patcher's key). */
  written?: string;
  /** A control's alias: what the template author calls the field. */
  label?: string;
  /** A control's placeholder text: what the author wrote as guidance. */
  hint?: string;
  location: PlaceholderLocation;
  /** A block-level control holds paragraphs; an inline one sits inside a paragraph. */
  block?: boolean;
  supported: boolean;
  reason?: string;
  /** The level of the nearest heading above a body control (0 when there is none). */
  headingLevel: number;
};

/** Style ids by role, resolved from style names; undefined when the template lacks the style. */
export type StyleMap = {
  title?: string;
  /** Index 1..6. */
  heading: (string | undefined)[];
  /** Index by list level 0..3 ("List Bullet", "List Bullet 2", ...). */
  listBullet: (string | undefined)[];
  listNumber: (string | undefined)[];
  listParagraph?: string;
  quote?: string;
  caption?: string;
  code?: string;
  /** Character style for links. */
  hyperlink?: string;
  /** Table style. */
  table?: string;
};

export type TemplateCheck = { ok: boolean; detail: string };

export type TemplateInspection = {
  syntax: "controls" | "braces" | "mixed" | "none";
  placeholders: Placeholder[];
  /** Where a whole document goes: a rich control with a content tag, else `{{content}}`. */
  contentPlaceholder?: Placeholder;
  styles: StyleMap;
  /** The abstract numbering the template's list styles link to, when they do. */
  listNumbering: { bullet?: number; number?: number };
  /** The document default language, e.g. sv-SE. */
  language?: string;
  /** Usable page area in points, the smallest over the template's sections. */
  page: { width: number; height: number };
  checks: Record<string, TemplateCheck>;
};

export async function part(zip: Zip, name: string): Promise<string | undefined> {
  return zip.file(name)?.async("string");
}

export async function parsedPart(zip: Zip, name: string): Promise<Element | undefined> {
  const xml = await part(zip, name);
  return xml === undefined ? undefined : parseXml(xml);
}

/** Opens a Word file the user supplied: a bounded zip with a document part and no macros. */
export async function openWordTemplate(template: Buffer): Promise<Zip> {
  if (template.length < 2 || template.readUInt16LE(0) !== 0x4b50)
    throw new TemplateError("The template is not a Word (.docx) file.");
  assertZipWithinBounds(template, MAX_EXPANDED_BYTES);
  const JSZip = (await import("jszip")).default;
  const zip = await JSZip.loadAsync(template);
  const contentTypes = await part(zip, "[Content_Types].xml");
  if (!zip.file("word/document.xml") || !contentTypes)
    throw new TemplateError("The template is not a Word (.docx) file.");
  if (/macroEnabled|vbaProject/i.test(contentTypes))
    throw new TemplateError("The template contains macros and cannot be used.");
  return zip;
}

/** The header and footer parts, in a stable order. */
export function headerFooterParts(zip: Zip): { name: string; location: PlaceholderLocation }[] {
  return Object.keys(zip.files)
    .filter((name) => /^word\/(header|footer)\d*\.xml$/.test(name))
    .sort()
    .map((name) => ({ name, location: name.includes("header") ? "header" : "footer" }));
}

const normalise = (name: string | undefined) =>
  (name ?? "").toLowerCase().replace(/\s+/g, " ").trim();

/** Styles by role, from `word/styles.xml`. */
export function readStyles(styles: Element | undefined): {
  map: StyleMap;
  headingLevelOf: Map<string, number>;
  listNumIds: { bullet?: string; number?: string };
  language?: string;
} {
  const map: StyleMap = { heading: [], listBullet: [], listNumber: [] };
  const headingLevelOf = new Map<string, number>();
  const listNumIds: { bullet?: string; number?: string } = {};
  const root = styles && rootElement(styles);
  for (const style of findAll(root, "w:style")) {
    const id = attr(style, "w:styleId");
    const type = attr(style, "w:type") ?? "paragraph";
    const name = normalise(attr(find(style, "w:name"), "w:val"));
    if (!id || !name) continue;
    if (type === "paragraph") {
      const heading = /^heading (\d)$/.exec(name);
      const bullet = /^list bullet(?: (\d))?$/.exec(name);
      const number = /^list number(?: (\d))?$/.exec(name);
      if (heading) {
        map.heading[Number(heading[1])] = id;
        headingLevelOf.set(id, Number(heading[1]));
      } else if (bullet) map.listBullet[bullet[1] ? Number(bullet[1]) - 1 : 0] = id;
      else if (number) map.listNumber[number[1] ? Number(number[1]) - 1 : 0] = id;
      else if (name === "title") {
        map.title = id;
        headingLevelOf.set(id, 0);
      } else if (name === "list paragraph") map.listParagraph = id;
      else if (name === "quote") map.quote = id;
      else if (name === "caption") map.caption = id;
      else if (/^(code|kod)\b/.test(name) || name === "html preformatted") map.code ??= id;
      const numId = attr(at(style, "w:pPr", "w:numPr", "w:numId"), "w:val");
      if (numId && bullet && !bullet[1]) listNumIds.bullet = numId;
      if (numId && number && !number[1]) listNumIds.number = numId;
    } else if (type === "character" && name === "hyperlink") map.hyperlink = id;
    else if (type === "table" && name === "table grid") map.table = id;
  }
  const language = attr(at(root, "w:docDefaults", "w:rPrDefault", "w:rPr", "w:lang"), "w:val");
  return { map, headingLevelOf, listNumIds, language };
}

/** The abstract numbering each list style's numbering instance points at. */
function abstractNumbering(
  numbering: Element | undefined,
  listNumIds: { bullet?: string; number?: string },
): { bullet?: number; number?: number } {
  const root = numbering && rootElement(numbering);
  const abstractOf = new Map<string, number>();
  for (const num of findAll(root, "w:num")) {
    const id = attr(num, "w:numId");
    const abstractId = attr(find(num, "w:abstractNumId"), "w:val");
    if (id && abstractId !== undefined) abstractOf.set(id, Number(abstractId));
  }
  return {
    bullet: listNumIds.bullet ? abstractOf.get(listNumIds.bullet) : undefined,
    number: listNumIds.number ? abstractOf.get(listNumIds.number) : undefined,
  };
}

/** Usable page dimensions in points, the smallest over the sections of the document part. */
export function pageFromDocument(document: Element): { width: number; height: number } {
  const sections: Element[] = [];
  walk(rootElement(document), (node) => {
    if (node.name === "w:sectPr") sections.push(node);
  });
  const value = (node: Element | undefined, name: string, fallback: number) => {
    const raw = attr(node, name);
    return raw === undefined || !/^\d+$/.test(raw) ? fallback : Number(raw);
  };
  const sizes = (sections.length ? sections : [undefined]).map((section) => {
    const page = find(section, "w:pgSz");
    const margin = find(section, "w:pgMar");
    return {
      width:
        (value(page, "w:w", 11906) -
          value(margin, "w:left", 1440) -
          value(margin, "w:right", 1440) -
          value(margin, "w:gutter", 0)) /
        20,
      height:
        (value(page, "w:h", 16838) -
          value(margin, "w:top", 1440) -
          value(margin, "w:bottom", 1440)) /
        20,
    };
  });
  const width = Math.min(...sizes.map((s) => s.width));
  const height = Math.min(...sizes.map((s) => s.height));
  if (width < 72 || height < 200)
    throw new TemplateError("The template leaves too little room for document content.");
  return { width, height };
}

/** Conservative usable page dimensions, in points, for figures placed into a template. */
export async function pageContentSize(
  template: Buffer,
): Promise<{ width: number; height: number }> {
  const zip = await openWordTemplate(template);
  return pageFromDocument((await parsedPart(zip, "word/document.xml"))!);
}

/** The content controls of one part, in document order. */
export function controlsOf(
  root: Element,
  location: PlaceholderLocation,
  headingLevelOf: Map<string, number>,
): { placeholder: Placeholder; sdt: Element }[] {
  const found: { placeholder: Placeholder; sdt: Element }[] = [];
  let lastHeading = 0;
  const scan = (node: Element, inSdt: boolean, inParagraph: boolean) => {
    for (const child of children(node)) {
      if (child.type !== "element") continue;
      if (child.name === "w:p") {
        const style = attr(at(child, "w:pPr", "w:pStyle"), "w:val");
        const level = style === undefined ? undefined : headingLevelOf.get(style);
        if (level !== undefined && !inSdt) lastHeading = level;
        scan(child, inSdt, true);
        continue;
      }
      if (child.name !== "w:sdt") {
        scan(child, inSdt, inParagraph);
        continue;
      }
      const properties = find(child, "w:sdtPr");
      const tag = attr(find(properties, "w:tag"), "w:val")?.trim();
      if (tag) {
        const isText = !!find(properties, "w:text");
        const other = children(properties).find((p) => OTHER_CONTROL_TYPES.has(p.name ?? ""));
        const content = find(child, "w:sdtContent");
        const placeholder: Placeholder = {
          name: tag,
          syntax: "control",
          kind: isText || inParagraph ? "text" : "rich",
          label: attr(find(properties, "w:alias"), "w:val"),
          hint: find(properties, "w:showingPlcHdr")
            ? textOf(content).replace(/\s+/g, " ").trim() || undefined
            : undefined,
          location,
          block: !inParagraph,
          supported: true,
          headingLevel: lastHeading,
        };
        if (inSdt) {
          placeholder.supported = false;
          placeholder.reason = "nested inside another control";
        } else if (other) {
          placeholder.supported = false;
          placeholder.reason = `${other.name!.replace(/^w1?[45]?:/, "")} controls are not filled`;
        } else if (find(properties, "w:dataBinding")) {
          placeholder.supported = false;
          placeholder.reason = "bound to document data";
        } else if (placeholder.kind === "rich" && location !== "body") {
          placeholder.supported = false;
          placeholder.reason = `a rich control in the ${location} is not filled`;
        }
        found.push({ placeholder, sdt: child });
      }
      scan(find(child, "w:sdtContent") ?? child, true, inParagraph);
    }
  };
  scan(rootElement(root), false, false);
  return found;
}

/** The `{{name}}` placeholders of one part by location, as written. */
function bracesOf(root: Element): string[] {
  const written: string[] = [];
  walk(rootElement(root), (node) => {
    if (node.name !== "w:p") return;
    for (const match of textOf(node).matchAll(BRACES)) written.push(match[1]!);
    return false;
  });
  return written;
}

export async function inspectTemplate(input: Buffer | Zip): Promise<TemplateInspection> {
  const zip = Buffer.isBuffer(input) ? await openWordTemplate(input) : input;
  const document = (await parsedPart(zip, "word/document.xml"))!;
  const styles = readStyles(await parsedPart(zip, "word/styles.xml"));
  const listNumbering = abstractNumbering(
    await parsedPart(zip, "word/numbering.xml"),
    styles.listNumIds,
  );
  const parts: { root: Element; location: PlaceholderLocation }[] = [
    { root: document, location: "body" },
  ];
  for (const { name, location } of headerFooterParts(zip)) {
    const root = await parsedPart(zip, name);
    if (root) parts.push({ root, location });
  }
  const placeholders: Placeholder[] = [];
  const bracesLocation = new Map<string, PlaceholderLocation>();
  for (const { root, location } of parts) {
    placeholders.push(
      ...controlsOf(root, location, styles.headingLevelOf).map((c) => c.placeholder),
    );
    for (const written of bracesOf(root))
      if (!bracesLocation.has(written)) bracesLocation.set(written, location);
  }
  // The patcher finds placeholders Word split across runs too; locations come from the text.
  const bytes = Buffer.isBuffer(input)
    ? input
    : Buffer.from(await zip.generateAsync({ type: "nodebuffer" }));
  const written = [...new Set(await patchDetector({ data: bytes }))];
  for (const text of written)
    placeholders.push({
      name: text.trim(),
      written: text,
      syntax: "braces",
      kind: "text",
      location: bracesLocation.get(text) ?? "body",
      supported: true,
      headingLevel: 0,
    });
  const controls = placeholders.filter((p) => p.syntax === "control");
  const contentPlaceholder =
    controls.find(
      (p) => p.supported && p.kind === "rich" && CONTENT_TAGS.has(p.name.toLowerCase()),
    ) ?? placeholders.find((p) => p.syntax === "braces" && p.name === "content");
  const map = styles.map;
  const checks: Record<string, TemplateCheck> = {
    content_placeholder: contentPlaceholder
      ? {
          ok: true,
          detail:
            contentPlaceholder.syntax === "control"
              ? `rich control "${contentPlaceholder.label ?? contentPlaceholder.name}"`
              : "{{content}} paragraph",
        }
      : { ok: false, detail: "no content control or {{content}} paragraph: the body is replaced" },
    heading_styles: [1, 2, 3].every((level) => map.heading[level])
      ? { ok: true, detail: "heading 1-3 defined" }
      : {
          ok: false,
          detail: `missing heading styles: ${[1, 2, 3]
            .filter((level) => !map.heading[level])
            .map((level) => `heading ${level}`)
            .join(", ")}`,
        },
    title_style: map.title
      ? { ok: true, detail: "title style defined" }
      : { ok: false, detail: "no title style: the title uses Word's default" },
    list_styles:
      map.listBullet[0] && map.listNumber[0]
        ? { ok: true, detail: "list bullet and list number defined" }
        : { ok: false, detail: "no list styles: Eneo's list formatting is used" },
    table_style: map.table
      ? { ok: true, detail: "table grid defined" }
      : { ok: false, detail: "no table grid style: tables get plain borders" },
    language: styles.language
      ? { ok: true, detail: styles.language }
      : { ok: false, detail: "no document language: set it in Word for accessibility" },
  };
  return {
    syntax:
      controls.length && written.length
        ? "mixed"
        : controls.length
          ? "controls"
          : written.length
            ? "braces"
            : "none",
    placeholders,
    contentPlaceholder,
    styles: map,
    listNumbering,
    language: styles.language,
    page: pageFromDocument(document),
    checks,
  };
}

/** The serialisable part of an inspection, for callers outside the sandbox. */
export function toReport(inspection: TemplateInspection): TemplateReport {
  return {
    syntax: inspection.syntax,
    placeholders: inspection.placeholders.map(
      ({ name, syntax, kind, label, hint, location, supported, reason }) => ({
        name,
        syntax,
        kind,
        ...(label !== undefined ? { label } : {}),
        ...(hint !== undefined ? { hint } : {}),
        location,
        supported,
        ...(reason !== undefined ? { reason } : {}),
      }),
    ),
    checks: inspection.checks,
    ...(inspection.language !== undefined ? { language: inspection.language } : {}),
  };
}
