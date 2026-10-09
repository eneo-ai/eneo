// Runs inside sandbox children only. The PDF "template" is the organisation's profile read
// from the Word file the document was already rendered into: page size and margins, body
// and heading faces (fonts, sizes, colours, with theme fonts and colours resolved), and the
// header and footer with their placeholders filled, page-number fields turned into counters
// and the first picture (the logo) exported. A Word font maps to the metric-compatible face
// the runtime image ships, so a Calibri template lays out as in Word.
import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import { bandRows, type Band, type BandSegment } from "./html";
import {
  headerFooterParts,
  openWordTemplate,
  parsedPart,
  readStyles,
  type StyleMap,
  type Zip,
} from "./word/inspect";
import { at, attr, children, find, findAll, rootElement, walk, type Element } from "./word/ooxml";

export type Face = {
  font?: string;
  sizePt?: number;
  color?: string;
  bold?: boolean;
  italic?: boolean;
  /** Paragraph spacing, for paragraph styles. */
  beforePt?: number;
  afterPt?: number;
};
export type PdfProfile = {
  page: {
    widthMm: number;
    heightMm: number;
    marginMm: { top: number; right: number; bottom: number; left: number };
    /** Distance from the page edge to the header and to the footer. */
    headerMm: number;
    footerMm: number;
  };
  /** The line height is a CSS value: a factor of the font size, or a length. */
  body: Face & { lineHeight?: string };
  title: Face;
  /** Index 1..3. */
  headings: Face[];
  header?: Band;
  footer?: Band;
};

const TWIPS_PER_MM = 1440 / 25.4;
const EMU_PER_PT = 12700;
/** Fonts common in municipal templates and the metric-compatible faces the image installs. */
const SUBSTITUTES: Record<string, string> = {
  calibri: "Carlito",
  cambria: "Caladea",
  arial: "Liberation Sans",
  helvetica: "Liberation Sans",
  "times new roman": "Liberation Serif",
  "courier new": "Liberation Mono",
  georgia: "DejaVu Serif",
  verdana: "DejaVu Sans",
  tahoma: "DejaVu Sans",
  "segoe ui": "DejaVu Sans",
  consolas: "DejaVu Sans Mono",
};
const SERIF = /georgia|times|cambria|garamond|book antiqua|palatino|serif/i;
const MONO = /courier|consolas|mono/i;

/** A CSS font-family list: the Word font, its substitute, and a generic family. */
export function fontStack(font: string | undefined): string {
  if (!font) return '"Carlito", "Calibri", "Liberation Sans", sans-serif';
  const substitute = SUBSTITUTES[font.toLowerCase()];
  const generic = MONO.test(font) ? "monospace" : SERIF.test(font) ? "serif" : "sans-serif";
  return [font, substitute, generic]
    .filter((name): name is string => !!name)
    .map((name) => (name.includes(" ") || /[A-Z]/.test(name) ? `"${name}"` : name))
    .join(", ");
}

function themeFonts(theme: Element | undefined): { major?: string; minor?: string } {
  const scheme = at(theme && rootElement(theme), "a:themeElements", "a:fontScheme");
  return {
    major: attr(at(scheme, "a:majorFont", "a:latin"), "typeface") || undefined,
    minor: attr(at(scheme, "a:minorFont", "a:latin"), "typeface") || undefined,
  };
}

function themeColors(theme: Element | undefined): Map<string, string> {
  const colors = new Map<string, string>();
  const scheme = at(theme && rootElement(theme), "a:themeElements", "a:clrScheme");
  for (const entry of children(scheme)) {
    if (!entry.name) continue;
    const value = attr(find(entry, "a:srgbClr"), "val") ?? attr(find(entry, "a:sysClr"), "lastClr");
    if (value) colors.set(entry.name.replace(/^a:/, ""), value.toLowerCase());
  }
  // Word's names for the scheme's first four colours.
  for (const [alias, name] of [
    ["text1", "dk1"],
    ["background1", "lt1"],
    ["text2", "dk2"],
    ["background2", "lt2"],
  ] as const)
    if (colors.has(name)) colors.set(alias, colors.get(name)!);
  return colors;
}

type Theme = { fonts: { major?: string; minor?: string }; colors: Map<string, string> };

function onOff(node: Element | undefined): boolean | undefined {
  if (!node) return undefined;
  const value = attr(node, "w:val");
  return value === undefined || !["0", "false", "off"].includes(value);
}

/** The face a run-properties element describes, with theme references resolved. */
function faceOf(properties: Element | undefined, theme: Theme): Face {
  if (!properties) return {};
  const face: Face = {};
  const fonts = find(properties, "w:rFonts");
  const themed = attr(fonts, "w:asciiTheme");
  const font =
    attr(fonts, "w:ascii") ??
    (themed?.startsWith("major") ? theme.fonts.major : themed ? theme.fonts.minor : undefined);
  if (font) face.font = font;
  const size = attr(find(properties, "w:sz"), "w:val");
  if (size && /^\d+$/.test(size)) face.sizePt = Number(size) / 2;
  const color = find(properties, "w:color");
  const themeColor = attr(color, "w:themeColor");
  const value = attr(color, "w:val");
  const resolved =
    (themeColor && theme.colors.get(themeColor)) ??
    (value && /^[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : undefined);
  if (resolved) face.color = `#${resolved}`;
  const bold = onOff(find(properties, "w:b"));
  if (bold !== undefined) face.bold = bold;
  const italic = onOff(find(properties, "w:i"));
  if (italic !== undefined) face.italic = italic;
  return face;
}

/** Paragraph spacing before and after, from a paragraph-properties element. */
function spacingOf(properties: Element | undefined): Pick<Face, "beforePt" | "afterPt"> {
  const spacing = find(properties, "w:spacing");
  const points = (name: string) => {
    const raw = attr(spacing, name);
    return raw && /^\d+$/.test(raw) ? Number(raw) / 20 : undefined;
  };
  const before = points("w:before");
  const after = points("w:after");
  return {
    ...(before !== undefined ? { beforePt: before } : {}),
    ...(after !== undefined ? { afterPt: after } : {}),
  };
}

/** Word's line spacing as a CSS line height. Single spacing in Word is about 1.15 times the font size. */
function lineHeightOf(properties: Element | undefined): string | undefined {
  const spacing = find(properties, "w:spacing");
  const raw = attr(spacing, "w:line");
  if (!raw || !/^\d+$/.test(raw) || Number(raw) <= 0) return undefined;
  const rule = attr(spacing, "w:lineRule") ?? "auto";
  return rule === "auto"
    ? ((Number(raw) / 240) * 1.15).toFixed(2)
    : `${(Number(raw) / 20).toFixed(1)}pt`;
}

/** The face of a paragraph style, following `basedOn` so inherited settings count. */
function styleFace(styles: Element | undefined, id: string | undefined, theme: Theme): Face {
  if (!id) return {};
  const byId = new Map(
    findAll(styles && rootElement(styles), "w:style").map((style) => [
      attr(style, "w:styleId"),
      style,
    ]),
  );
  const chain: Element[] = [];
  let current = byId.get(id);
  while (current && chain.length < 8) {
    chain.unshift(current);
    current = byId.get(attr(find(current, "w:basedOn"), "w:val"));
  }
  return chain.reduce<Face>(
    (face, style) => ({
      ...face,
      ...faceOf(find(style, "w:rPr"), theme),
      ...spacingOf(find(style, "w:pPr")),
    }),
    {},
  );
}

/** The face a header or footer is set in: its first paragraph's style under the first run's own formatting. */
function bandFace(part: Element, styles: Element | undefined, theme: Theme): Face {
  let paragraph: Element | undefined;
  let run: Element | undefined;
  walk(rootElement(part), (node) => {
    if (node.name === "w:p" && !paragraph) paragraph = node;
    if (node.name === "w:r" && !run && find(node, "w:t")) run = node;
    return !run;
  });
  const styleId = attr(at(paragraph, "w:pPr", "w:pStyle"), "w:val");
  const { beforePt: _before, afterPt: _after, ...face } = {
    ...styleFace(styles, styleId, theme),
    ...faceOf(find(run, "w:rPr"), theme),
  };
  return face;
}

function relationTargets(rels: Element | undefined): Map<string, string> {
  return new Map(
    findAll(rels && rootElement(rels), "Relationship").map((relationship) => [
      attr(relationship, "Id") ?? "",
      attr(relationship, "Target") ?? "",
    ]),
  );
}

/** The text of a header or footer paragraph, with page-number fields as counters and tabs as segment breaks. */
function paragraphSegments(paragraph: Element): (string | { counter: "page" | "pages" } | "\t")[] {
  const parts: (string | { counter: "page" | "pages" } | "\t")[] = [];
  let field: "none" | "instruction" | "result" = "none";
  let instruction = "";
  const counterFor = (text: string) => {
    const name = text.trim().split(/\s+/)[0]?.toUpperCase();
    return name === "PAGE"
      ? "page"
      : name === "NUMPAGES" || name === "SECTIONPAGES"
        ? "pages"
        : undefined;
  };
  const visit = (node: Element) => {
    for (const child of children(node)) {
      if (child.type !== "element") continue;
      switch (child.name) {
        case "w:fldSimple": {
          const counter = counterFor(attr(child, "w:instr") ?? "");
          if (counter) parts.push({ counter });
          else visit(child);
          break;
        }
        case "w:fldChar": {
          const type = attr(child, "w:fldCharType");
          if (type === "begin") {
            field = "instruction";
            instruction = "";
          } else if (type === "separate") field = "result";
          else if (type === "end") {
            const counter = counterFor(instruction);
            if (counter) parts.push({ counter });
            field = "none";
          }
          break;
        }
        case "w:instrText":
          if (field === "instruction")
            instruction += children(child)
              .map((text) => String(text.text ?? ""))
              .join("");
          break;
        case "w:t":
          if (field === "none") {
            // A literal tab in the text separates segments like a w:tab does.
            const text = children(child)
              .map((text) => String(text.text ?? ""))
              .join("");
            text.split("\t").forEach((piece, index) => {
              if (index) parts.push("\t");
              if (piece) parts.push(piece);
            });
          }
          break;
        case "w:tab":
          if (field === "none") parts.push("\t");
          break;
        case "w:br":
        case "w:cr":
          if (field === "none") parts.push(" ");
          break;
        case "w:drawing":
        case "w:pict":
          break;
        default:
          visit(child);
      }
    }
  };
  visit(paragraph);
  return parts;
}

/** The header or footer as aligned segments, from its paragraphs. */
function bandOf(part: Element): BandSegment[] {
  const segments: BandSegment[] = [];
  const root = rootElement(part);
  const paragraphs: Element[] = [];
  walk(root, (node) => {
    if (node.name === "w:p") {
      paragraphs.push(node);
      return false;
    }
  });
  for (const paragraph of paragraphs) {
    const justification = attr(at(paragraph, "w:pPr", "w:jc"), "w:val");
    const align =
      justification === "center"
        ? "center"
        : justification === "right" || justification === "end"
          ? "right"
          : "left";
    const groups: (string | { counter: "page" | "pages" })[][] = [[]];
    for (const part of paragraphSegments(paragraph)) {
      if (part === "\t") groups.push([]);
      else groups[groups.length - 1]!.push(part);
    }
    const merged = groups
      .map((group) =>
        group.reduce<(string | { counter: "page" | "pages" })[]>((acc, part) => {
          const last = acc[acc.length - 1];
          if (typeof part === "string" && typeof last === "string")
            acc[acc.length - 1] = last + part;
          else acc.push(part);
          return acc;
        }, []),
      )
      .map((group) => group.filter((part) => typeof part !== "string" || part.trim()))
      .filter((group) => group.length);
    if (!merged.length) continue;
    const aligns: BandSegment["align"][] =
      merged.length === 1
        ? [align]
        : merged.length === 2
          ? ["left", "right"]
          : ["left", "center", "right"];
    merged.slice(0, 3).forEach((parts, index) => segments.push({ align: aligns[index]!, parts }));
  }
  return segments;
}

/** The first picture of a part, written to the assets directory, with its printed size. */
async function logoOf(
  zip: Zip,
  partName: string,
  part: Element,
  assetsDir: string,
): Promise<Band["logo"]> {
  let found: { id: string; cx: number; cy: number } | undefined;
  walk(rootElement(part), (node) => {
    if (found) return false;
    if (node.name !== "w:drawing") return;
    let embed: string | undefined;
    let cx = 0;
    let cy = 0;
    walk(node, (inner) => {
      if (inner.name === "wp:extent" && !cx) {
        cx = Number(attr(inner, "cx") ?? 0);
        cy = Number(attr(inner, "cy") ?? 0);
      }
      if (inner.name === "a:blip" && !embed) embed = attr(inner, "r:embed");
    });
    if (embed && cx && cy) found = { id: embed, cx, cy };
    return false;
  });
  if (!found) return undefined;
  const relsName = partName.replace(/^word\/(.+)$/, "word/_rels/$1.rels");
  const target = relationTargets(await parsedPart(zip, relsName)).get(found.id);
  if (!target) return undefined;
  const mediaName = target.startsWith("/") ? target.slice(1) : `word/${target}`;
  const extension = /\.(png|jpe?g)$/i.exec(mediaName)?.[1]?.toLowerCase();
  const bytes = extension && (await zip.file(mediaName)?.async("nodebuffer"));
  if (!bytes) return undefined;
  const file = `logo.${extension === "jpeg" ? "jpg" : extension}`;
  await writeFile(join(assetsDir, file), bytes, { mode: 0o600 });
  return { file, widthPt: found.cx / EMU_PER_PT, heightPt: found.cy / EMU_PER_PT };
}

/** Reads the profile of a rendered Word file. Pictures it exports go to `assetsDir`. */
export async function pdfProfile(docx: Buffer, assetsDir: string): Promise<PdfProfile> {
  const zip = await openWordTemplate(docx);
  const document = (await parsedPart(zip, "word/document.xml"))!;
  const styles = await parsedPart(zip, "word/styles.xml");
  const themePart = await parsedPart(zip, "word/theme/theme1.xml");
  const theme: Theme = { fonts: themeFonts(themePart), colors: themeColors(themePart) };
  const stylesRoot = styles && rootElement(styles);
  const map: StyleMap = readStyles(styles).map;

  const defaults = faceOf(at(stylesRoot, "w:docDefaults", "w:rPrDefault", "w:rPr"), theme);
  const normalId =
    findAll(stylesRoot, "w:style").find(
      (style) => attr(style, "w:type") === "paragraph" && attr(style, "w:default") === "1",
    ) ?? undefined;
  const defaultParagraph = at(stylesRoot, "w:docDefaults", "w:pPrDefault", "w:pPr");
  const normal = {
    ...faceOf(find(normalId, "w:rPr"), theme),
    ...spacingOf(find(normalId, "w:pPr")),
  };
  const body: PdfProfile["body"] = {
    font: theme.fonts.minor,
    sizePt: 11,
    ...defaults,
    ...spacingOf(defaultParagraph),
    ...normal,
  };
  const lineHeight = lineHeightOf(find(normalId, "w:pPr")) ?? lineHeightOf(defaultParagraph);
  if (lineHeight) body.lineHeight = lineHeight;

  const page = (() => {
    let section: Element | undefined;
    walk(rootElement(document), (node) => {
      if (node.name === "w:sectPr") section = node;
    });
    const size = find(section, "w:pgSz");
    const margin = find(section, "w:pgMar");
    const mm = (node: Element | undefined, name: string, fallback: number) => {
      const raw = attr(node, name);
      return (raw && /^\d+$/.test(raw) ? Number(raw) : fallback) / TWIPS_PER_MM;
    };
    return {
      section,
      widthMm: mm(size, "w:w", 11906),
      heightMm: mm(size, "w:h", 16838),
      marginMm: {
        top: mm(margin, "w:top", 1440),
        right: mm(margin, "w:right", 1440),
        bottom: mm(margin, "w:bottom", 1440),
        left: mm(margin, "w:left", 1440),
      },
      headerMm: mm(margin, "w:header", 708),
      footerMm: mm(margin, "w:footer", 708),
    };
  })();

  const bands: { header?: Band; footer?: Band } = {};
  const documentRels = relationTargets(await parsedPart(zip, "word/_rels/document.xml.rels"));
  const known = new Set(headerFooterParts(zip).map((p) => p.name));
  for (const kind of ["header", "footer"] as const) {
    const reference = findAll(page.section, `w:${kind}Reference`).find(
      (node) => (attr(node, "w:type") ?? "default") === "default",
    );
    const target = reference && documentRels.get(attr(reference, "r:id") ?? "");
    const partName = target && `word/${target.replace(/^\/?word\//, "")}`;
    if (!partName || !known.has(partName)) continue;
    const part = await parsedPart(zip, partName);
    if (!part) continue;
    const segments = bandOf(part);
    const logo = kind === "header" ? await logoOf(zip, partName, part, assetsDir) : undefined;
    const face = bandFace(part, styles, theme);
    if (segments.length || logo)
      bands[kind] = {
        segments,
        ...(Object.keys(face).length ? { face } : {}),
        ...(logo ? { logo } : {}),
      };
  }

  return {
    page: {
      widthMm: page.widthMm,
      heightMm: page.heightMm,
      marginMm: page.marginMm,
      headerMm: page.headerMm,
      footerMm: page.footerMm,
    },
    body,
    title: styleFace(styles, map.title, theme),
    headings: [{}, ...[1, 2, 3].map((level) => styleFace(styles, map.heading[level], theme))],
    ...bands,
  };
}

function faceCss(face: Face, fallbackSize: number): string {
  const rules: string[] = [];
  if (face.font) rules.push(`font-family: ${fontStack(face.font)}`);
  rules.push(`font-size: ${face.sizePt ?? fallbackSize}pt`);
  if (face.color) rules.push(`color: ${face.color}`);
  if (face.bold !== undefined) rules.push(`font-weight: ${face.bold ? 700 : 400}`);
  if (face.italic !== undefined) rules.push(`font-style: ${face.italic ? "italic" : "normal"}`);
  return rules.join("; ");
}

const PT_PER_MM = 72 / 25.4;

/** The height a band takes on the page, in points, for sizing the margin it sits in. */
function bandHeightPt(band: Band | undefined, fontSizePt: number): number {
  if (!band) return 0;
  const rows = bandRows(band.segments).length;
  return (band.logo ? band.logo.heightPt + 4 : 0) + rows * fontSizePt * 1.3;
}

/** The stylesheet for the document: the profile on top of Eneo's base layout. */
export function profileCss(profile: PdfProfile): string {
  const { page, body } = profile;
  const bodySize = body.sizePt ?? 11;
  const bandSize = (band: Band | undefined) => band?.face?.sizePt ?? Math.max(8, bodySize - 1);
  // Word places the header at its distance from the page edge and pushes the body down when
  // the header is taller than the margin leaves; the footer grows upward the same way.
  const headerPt = bandHeightPt(profile.header, bandSize(profile.header));
  const footerPt = bandHeightPt(profile.footer, bandSize(profile.footer));
  const topMm = Math.max(page.marginMm.top, page.headerMm + (headerPt + 6) / PT_PER_MM);
  const bottomMm = Math.max(page.marginMm.bottom, page.footerMm + (footerPt + 6) / PT_PER_MM);
  const contentWidthMm = page.widthMm - page.marginMm.left - page.marginMm.right;
  const header = profile.header
    ? `  @top-left { content: element(page-header); width: ${contentWidthMm.toFixed(2)}mm; vertical-align: top; padding-top: ${page.headerMm.toFixed(2)}mm; }\n`
    : "";
  const footer = profile.footer
    ? `  @bottom-left { content: element(page-footer); width: ${contentWidthMm.toFixed(2)}mm; vertical-align: bottom; padding-bottom: ${page.footerMm.toFixed(2)}mm; }\n`
    : "";
  const bandCss = (id: string, band: Band | undefined) =>
    `#${id} { position: running(${id}); ${faceCss(band?.face ?? {}, bandSize(band))}; }\n`;
  const heading = (level: number, fallbackSize: number) => {
    const face = profile.headings[level] ?? {};
    return `h${level} { ${faceCss(face, bodySize * fallbackSize)}; margin: ${face.beforePt ?? 14}pt 0 ${face.afterPt ?? 6}pt; }`;
  };
  return `@page {
  size: ${page.widthMm.toFixed(2)}mm ${page.heightMm.toFixed(2)}mm;
  margin: ${topMm.toFixed(2)}mm ${page.marginMm.right.toFixed(2)}mm ${bottomMm.toFixed(2)}mm ${page.marginMm.left.toFixed(2)}mm;
${header}${footer}}
html {
  font-family: ${fontStack(body.font)};
  font-size: ${bodySize}pt;
  line-height: ${body.lineHeight ?? "1.3"};
  color: ${body.color ?? "#111111"};
}
body { margin: 0; }
.document { overflow-wrap: anywhere; }
${bandCss("page-header", profile.header)}${bandCss("page-footer", profile.footer)}.band { color: ${body.color ?? "#111111"}; }
.band-logo { display: block; margin-bottom: 4pt; }
.band-row { display: table; width: 100%; table-layout: fixed; border-collapse: collapse; }
.band-row > span { display: table-cell; vertical-align: bottom; }
.band-left { text-align: left; }
.band-center { text-align: center; }
.band-right { text-align: right; }
.counter-page::before { content: counter(page); }
.counter-pages::before { content: counter(pages); }
h1, h2, h3, h4, h5, h6 { line-height: 1.2; break-after: avoid; }
${heading(1, 1.6)}
${heading(2, 1.3)}
${heading(3, 1.1)}
h4, h5, h6 { font-size: ${bodySize}pt; margin: ${profile.headings[3]?.beforePt ?? 14}pt 0 ${profile.headings[3]?.afterPt ?? 6}pt; }
h1.title { ${faceCss(profile.title, bodySize * 2.2)}; margin: ${profile.title.beforePt ?? 0}pt 0 ${profile.title.afterPt ?? 14}pt; }
p, ul, ol, pre, table, figure, blockquote { margin: ${body.beforePt ?? 0}pt 0 ${body.afterPt ?? 8}pt; }
ul, ol { padding-left: 18pt; }
li { margin: 0 0 2pt; }
li > p { margin: 0; }
a { color: inherit; text-decoration: underline; }
code { font-family: ${fontStack("Consolas")}; font-size: 0.92em; background: #f3f3f3; padding: 0 2pt; }
pre {
  font-family: ${fontStack("Consolas")};
  font-size: 0.9em;
  background: #f3f3f3;
  border: 0.5pt solid #d0d0d0;
  padding: 6pt;
  white-space: pre-wrap;
}
pre code { background: transparent; padding: 0; }
blockquote { border-left: 2pt solid #999999; padding-left: 10pt; margin-left: 0; }
table { border-collapse: collapse; width: 100%; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th, td { border: 0.5pt solid #bfbfbf; padding: 3pt 5pt; text-align: left; vertical-align: top; }
th { font-weight: 700; background: #f3f3f3; }
figure { text-align: center; break-inside: avoid; }
figure img { max-width: 100%; height: auto; }
figcaption { font-size: 0.9em; font-style: italic; margin-top: 3pt; }
hr { border: 0; border-top: 0.5pt solid #999999; margin: 10pt 0; }
.page-break { break-after: page; height: 0; }
s { color: #555555; }
`;
}
