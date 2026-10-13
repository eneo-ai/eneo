// Runs inside sandbox children only (and behind the template download route). Eneo's own
// document template: the one every Word file is rendered into when no other is given, and
// the file an administrator downloads to adapt in Word. It is built with the docx library,
// so it carries real styles (Title, Heading 1-3, List Bullet, List Number, Quote, Caption,
// Code, Hyperlink), the document language, a header and footer with placeholders, and a
// rich content control tagged `content` where the document goes: the same conventions a
// hand-made template is expected to follow.
import {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  Header,
  Packer,
  PageNumber,
  Paragraph,
  TabStopPosition,
  TabStopType,
  TextRun,
} from "docx";
import { BULLETS, LIST_CONFIG, NUMBERS } from "../docx";
import { wrapInRichControl } from "./controls";
import { parseXml, rootElement, serializeXml } from "./ooxml";

export type TemplateLanguage = "sv" | "en";
export const LANGUAGE_TAGS: Record<TemplateLanguage, string> = { sv: "sv-SE", en: "en-GB" };
const cache = new Map<TemplateLanguage, Promise<Buffer>>();

const TEXT = {
  sv: {
    title: "Eneo dokumentmall",
    control: "Innehåll",
    hint: "Dokumentets innehåll läggs här.",
    page: "Sida ",
    of: " av ",
  },
  en: {
    title: "Eneo document template",
    control: "Content",
    hint: "The document's content goes here.",
    page: "Page ",
    of: " of ",
  },
};

async function build(language: TemplateLanguage): Promise<Buffer> {
  const text = TEXT[language];
  const listStyle = (
    id: string,
    name: string,
    reference: string,
    level: number,
  ): NonNullable<
    NonNullable<ConstructorParameters<typeof Document>[0]["styles"]>["paragraphStyles"]
  >[number] => ({
    id,
    name,
    basedOn: "Normal",
    next: id,
    quickFormat: true,
    paragraph: { numbering: { reference, level }, spacing: { after: 60 } },
  });
  const doc = new Document({
    creator: "Eneo",
    title: text.title,
    numbering: { config: LIST_CONFIG },
    styles: {
      default: {
        document: {
          run: { font: "Calibri", size: 22, language: { value: LANGUAGE_TAGS[language] } },
          paragraph: { spacing: { after: 120, line: 276 } },
        },
      },
      paragraphStyles: [
        listStyle("ListBullet", "List Bullet", BULLETS, 0),
        listStyle("ListBullet2", "List Bullet 2", BULLETS, 1),
        listStyle("ListBullet3", "List Bullet 3", BULLETS, 2),
        listStyle("ListNumber", "List Number", NUMBERS, 0),
        listStyle("ListNumber2", "List Number 2", NUMBERS, 1),
        listStyle("ListNumber3", "List Number 3", NUMBERS, 2),
        {
          id: "Quote",
          name: "Quote",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          paragraph: {
            indent: { left: 720 },
            border: {
              left: { style: BorderStyle.SINGLE, size: 12, color: "999999", space: 8 },
            },
          },
        },
        {
          id: "Caption",
          name: "Caption",
          basedOn: "Normal",
          next: "Normal",
          run: { italics: true, size: 18 },
          paragraph: { alignment: AlignmentType.CENTER, spacing: { after: 160 } },
        },
        {
          id: "Code",
          name: "Code",
          basedOn: "Normal",
          next: "Code",
          run: { font: "Consolas", size: 18 },
          paragraph: { shading: { fill: "F2F2F2" }, spacing: { after: 0 } },
        },
      ],
    },
    sections: [
      {
        properties: {
          page: {
            size: { width: 11906, height: 16838 },
            margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
          },
        },
        headers: {
          default: new Header({
            children: [
              new Paragraph({
                alignment: AlignmentType.RIGHT,
                children: [new TextRun("{{organisation}}")],
              }),
            ],
          }),
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
                children: [
                  new TextRun("{{title}}"),
                  new TextRun(`\t${text.page}`),
                  new TextRun({ children: [PageNumber.CURRENT] }),
                  new TextRun(text.of),
                  new TextRun({ children: [PageNumber.TOTAL_PAGES] }),
                ],
              }),
            ],
          }),
        },
        children: [new Paragraph("{{content}}")],
      },
    ],
  });
  const packed = Buffer.from(await Packer.toBuffer(doc));
  // The body placeholder becomes a rich content control, as in a template made in Word.
  const JSZip = (await import("jszip")).default;
  const zip = await JSZip.loadAsync(packed);
  const document = parseXml(await zip.file("word/document.xml")!.async("string"));
  if (
    !wrapInRichControl(rootElement(document), "content", {
      tag: "content",
      alias: text.control,
      hint: text.hint,
    })
  )
    throw new Error("The built-in template lost its content paragraph.");
  zip.file("word/document.xml", serializeXml(document));
  return Buffer.from(await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

/** Eneo's built-in template in the given language, built once per process. */
export function builtinTemplate(language: TemplateLanguage): Promise<Buffer> {
  let template = cache.get(language);
  if (!template) {
    template = build(language);
    cache.set(language, template);
  }
  return template;
}
