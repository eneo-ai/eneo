// Runs inside sandbox children only. Puts rendered content into a Word template: the
// template keeps its styles, numbering, headers, footers, page setup and relationships; the
// rendered document contributes its body paragraphs, the list definitions they use and the
// hyperlinks they point at. Both packages are well-formed OOXML (one made by Word, one by the
// docx library), so the parts are spliced as XML text rather than parsed into a tree.
import { assertZipWithinBounds } from "../../tabular/zip-guard";

export class TemplateError extends Error {}

/** A paragraph whose text is exactly this marks where the content goes. */
export const CONTENT_PLACEHOLDER = "{{content}}";
const MAX_EXPANDED_BYTES = 64 * 1024 * 1024;
const HYPERLINK_TYPE =
  "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink";
const NUMBERING_TYPE =
  "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering";
const NUMBERING_CONTENT_TYPE =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml";

type Zip = Awaited<ReturnType<(typeof import("jszip"))["loadAsync"]>>;

async function part(zip: Zip, name: string): Promise<string | undefined> {
  return zip.file(name)?.async("string");
}

/** The children of `<w:body>` split into content and the trailing section properties. */
function splitBody(documentXml: string): { content: string; sectPr: string } {
  const open = documentXml.indexOf("<w:body>");
  const close = documentXml.lastIndexOf("</w:body>");
  if (open < 0 || close < 0) throw new TemplateError("The template has no document body.");
  const body = documentXml.slice(open + "<w:body>".length, close);
  const sect = body.search(/<w:sectPr(?=[\s>/])[^>]*(?:\/>|>[\s\S]*<\/w:sectPr>)\s*$/);
  return sect < 0
    ? { content: body, sectPr: "" }
    : { content: body.slice(0, sect), sectPr: body.slice(sect) };
}

function textOf(paragraphXml: string): string {
  return paragraphXml
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Replaces the placeholder paragraph, or the whole content when the template has none. */
function placeContent(templateContent: string, rendered: string): string {
  let placed = false;
  const result = templateContent.replace(
    /<w:p(?=[\s>])[^>]*(?:\/>|>[\s\S]*?<\/w:p>)/g,
    (paragraph) => {
      if (placed || textOf(paragraph) !== CONTENT_PLACEHOLDER) return paragraph;
      placed = true;
      return rendered;
    },
  );
  return placed ? result : rendered;
}

function maxId(xml: string, pattern: RegExp): number {
  let max = -1;
  for (const match of xml.matchAll(pattern)) max = Math.max(max, Number(match[1]));
  return max;
}

/** Shifts every list id the rendered document defines or references past the template's. */
function mergeNumbering(
  content: string,
  renderedNumbering: string | undefined,
  templateNumbering: string | undefined,
): { content: string; numbering: string | undefined } {
  if (!renderedNumbering || !/<w:numId /.test(content))
    return { content, numbering: templateNumbering };
  const offset =
    templateNumbering === undefined
      ? 0
      : Math.max(
          maxId(templateNumbering, /w:abstractNumId="(\d+)"/g),
          maxId(templateNumbering, /w:numId="(\d+)"/g),
        ) + 1;
  const shift = (xml: string, attribute: string) =>
    xml.replace(
      new RegExp(`${attribute}="(\\d+)"`, "g"),
      (_, id) => `${attribute}="${Number(id) + offset}"`,
    );
  const shiftedContent = shift(content, "w:numId w:val");
  const shiftedNumbering = shift(
    shift(shift(renderedNumbering, "w:abstractNumId"), "w:numId"),
    "w:abstractNumId w:val",
  );
  if (templateNumbering === undefined)
    return { content: shiftedContent, numbering: shiftedNumbering };
  const abstractNums =
    shiftedNumbering.match(/<w:abstractNum(?=[\s>])[\s\S]*?<\/w:abstractNum>/g) ?? [];
  const nums = shiftedNumbering.match(/<w:num(?=[\s>])[\s\S]*?<\/w:num>/g) ?? [];
  let merged = templateNumbering;
  // Schema order: every abstractNum before the first num.
  const firstNum = merged.search(/<w:num(?=[\s>])/);
  merged =
    firstNum < 0
      ? merged.replace("</w:numbering>", `${abstractNums.join("")}</w:numbering>`)
      : merged.slice(0, firstNum) + abstractNums.join("") + merged.slice(firstNum);
  merged = merged.replace("</w:numbering>", `${nums.join("")}</w:numbering>`);
  return { content: shiftedContent, numbering: merged };
}

/** Carries the rendered hyperlinks into the template's relationships under fresh ids. */
function mergeHyperlinks(
  content: string,
  renderedRels: string | undefined,
  templateRels: string,
): { content: string; rels: string } {
  if (!renderedRels) return { content, rels: templateRels };
  const additions: string[] = [];
  let next = 1;
  let renamed = content;
  for (const match of renderedRels.matchAll(/<Relationship\b[^>]*\/>/g)) {
    const relationship = match[0];
    if (!relationship.includes(HYPERLINK_TYPE)) continue;
    const id = /\bId="([^"]+)"/.exec(relationship)?.[1];
    if (!id) continue;
    const fresh = `rIdEneo${next++}`;
    renamed = renamed.replaceAll(`r:id="${id}"`, `r:id="${fresh}"`);
    additions.push(relationship.replace(`Id="${id}"`, `Id="${fresh}"`));
  }
  return {
    content: renamed,
    rels: additions.length
      ? templateRels.replace("</Relationships>", `${additions.join("")}</Relationships>`)
      : templateRels,
  };
}

/** Namespace declarations the rendered root carries that the template root lacks. */
function mergeNamespaces(templateDocument: string, renderedDocument: string): string {
  const root = /<w:document\b[^>]*>/.exec(templateDocument);
  const renderedRoot = /<w:document\b[^>]*>/.exec(renderedDocument);
  if (!root || !renderedRoot) return templateDocument;
  let tag = root[0];
  for (const match of renderedRoot[0].matchAll(/\sxmlns:([\w-]+)="[^"]*"/g)) {
    if (!new RegExp(`\\sxmlns:${match[1]}=`).test(tag)) tag = tag.replace(/>$/, `${match[0]}>`);
  }
  return templateDocument.replace(root[0], tag);
}

/**
 * Renders `rendered` (a complete DOCX made by the docx library) into `template` (a DOCX the
 * user supplied). The result is the template with its body replaced by the rendered content,
 * or with the content in place of a paragraph reading `{{content}}`.
 */
export async function applyTemplate(rendered: Buffer, template: Buffer): Promise<Buffer> {
  if (template.length < 2 || template.readUInt16LE(0) !== 0x4b50)
    throw new TemplateError("The template is not a Word (.docx) file.");
  assertZipWithinBounds(template, MAX_EXPANDED_BYTES);
  const JSZip = (await import("jszip")).default;
  const zip = await JSZip.loadAsync(template);
  const templateDocument = await part(zip, "word/document.xml");
  const contentTypes = await part(zip, "[Content_Types].xml");
  const templateRels = await part(zip, "word/_rels/document.xml.rels");
  if (!templateDocument || !contentTypes || !templateRels)
    throw new TemplateError("The template is not a Word (.docx) file.");
  if (/macroEnabled|vbaProject/i.test(contentTypes))
    throw new TemplateError("The template contains macros and cannot be used.");

  const renderedZip = await JSZip.loadAsync(rendered);
  const renderedDocument = (await part(renderedZip, "word/document.xml")) ?? "";
  const numbering = mergeNumbering(
    splitBody(renderedDocument).content,
    await part(renderedZip, "word/numbering.xml"),
    await part(zip, "word/numbering.xml"),
  );
  const hyperlinks = mergeHyperlinks(
    numbering.content,
    await part(renderedZip, "word/_rels/document.xml.rels"),
    templateRels,
  );
  const body = splitBody(templateDocument);
  const document = mergeNamespaces(templateDocument, renderedDocument).replace(
    body.content + body.sectPr,
    placeContent(body.content, hyperlinks.content) + body.sectPr,
  );
  zip.file("word/document.xml", document);
  let rels = hyperlinks.rels;
  if (numbering.numbering !== undefined && !zip.file("word/numbering.xml")) {
    // The template had no lists: add the part, its relationship and its content type.
    rels = rels.replace(
      "</Relationships>",
      `<Relationship Id="rIdEneoNumbering" Type="${NUMBERING_TYPE}" Target="numbering.xml"/></Relationships>`,
    );
    zip.file(
      "[Content_Types].xml",
      contentTypes.replace(
        "</Types>",
        `<Override PartName="/word/numbering.xml" ContentType="${NUMBERING_CONTENT_TYPE}"/></Types>`,
      ),
    );
  }
  if (numbering.numbering !== undefined) zip.file("word/numbering.xml", numbering.numbering);
  zip.file("word/_rels/document.xml.rels", rels);
  return Buffer.from(await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}
