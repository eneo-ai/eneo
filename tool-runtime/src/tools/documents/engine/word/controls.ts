// Runs inside sandbox children only. Content controls are filled on the parsed tree. A text
// control gets its value written as runs that keep the formatting the control held. A rich
// control is reduced to a single `{{token}}` paragraph inside its own `w:sdtContent` (the
// control stays, so Word still shows the field), and the docx patcher then puts the rendered
// paragraphs where the token is; the patcher reads paragraphs anywhere, but not the runs
// inside an inline control, which is why text goes in directly. A control that gets an empty
// value is removed, as Flows does.
import {
  attr,
  children,
  clone,
  element,
  find,
  findAll,
  remove,
  walk,
  wordText,
  type Element,
} from "./ooxml";

/** The run properties of the first run below a node, without Word's placeholder style. */
function runProperties(node: Element | undefined): Element | undefined {
  let found: Element | undefined;
  if (node)
    walk(node, (child) => {
      if (found) return false;
      if (child.name === "w:r") {
        const properties = find(child, "w:rPr");
        if (properties) found = clone(properties);
        return false;
      }
    });
  if (!found) return undefined;
  for (const style of findAll(found, "w:rStyle"))
    if (/placeholder/i.test(attr(style, "w:val") ?? "")) remove(found, style);
  return children(found).length ? found : undefined;
}

function tokenRun(token: string, properties?: Element): Element {
  return element("w:r", {}, [...(properties ? [properties] : []), wordText(`{{${token}}}`)]);
}

/** One run holding the text, with a line break wherever the value has one. */
function textRun(value: string, properties?: Element): Element {
  const lines = value.split(/\r?\n/);
  return element("w:r", {}, [
    ...(properties ? [properties] : []),
    ...lines.flatMap((line, index) => [...(index ? [element("w:br")] : []), wordText(line)]),
  ]);
}

/** Writes a text value into a control, keeping the formatting of the run it held. */
export function placeValue(sdt: Element, value: string): void {
  const properties = find(sdt, "w:sdtPr");
  const content = find(sdt, "w:sdtContent") ?? element("w:sdtContent");
  if (!find(sdt, "w:sdtContent")) (sdt.elements ??= []).push(content);
  for (const marker of findAll(properties, "w:showingPlcHdr")) remove(properties!, marker);
  const run = textRun(value, runProperties(content));
  const block = children(content).some((child) => child.name === "w:p" || child.name === "w:tbl");
  const paragraphStyle = paragraphProperties(content);
  content.elements = block
    ? [element("w:p", {}, [...(paragraphStyle ? [paragraphStyle] : []), run])]
    : [run];
}

/** The paragraph properties of the first paragraph below a node (a block control's own look). */
function paragraphProperties(node: Element | undefined): Element | undefined {
  const paragraph = find(node, "w:p");
  const properties = find(paragraph, "w:pPr");
  return properties ? clone(properties) : undefined;
}

/**
 * Reduces a rich control to one `{{token}}` paragraph, which the patcher replaces wholesale
 * with the rendered paragraphs. (An inline control gets a run, for completeness.)
 */
export function placeToken(sdt: Element, token: string): void {
  const properties = find(sdt, "w:sdtPr");
  const content = find(sdt, "w:sdtContent") ?? element("w:sdtContent");
  if (!find(sdt, "w:sdtContent")) (sdt.elements ??= []).push(content);
  for (const marker of findAll(properties, "w:showingPlcHdr")) remove(properties!, marker);
  const run = tokenRun(token, runProperties(content));
  const block = children(content).some((child) => child.name === "w:p" || child.name === "w:tbl");
  const paragraphStyle = paragraphProperties(content);
  content.elements = block
    ? [element("w:p", {}, [...(paragraphStyle ? [paragraphStyle] : []), run])]
    : [run];
}

/** Removes a control from the part; an inline control leaves its paragraph in place. */
export function removeControl(root: Element, sdt: Element): void {
  walk(root, (node, parent) => {
    if (node === sdt && parent) remove(parent, sdt);
  });
}

/** Replaces the whole body (everything but the section properties) with one token paragraph. */
export function replaceBody(documentRoot: Element, token: string): void {
  const body = find(documentRoot, "w:body");
  if (!body) throw new Error("The template has no document body.");
  const section = [...children(body)].reverse().find((child) => child.name === "w:sectPr");
  body.elements = [element("w:p", {}, [tokenRun(token)]), ...(section ? [section] : [])];
}

/**
 * Wraps the paragraph reading `{{written}}` in a rich content control, so a generated
 * template shows the field the way Word's own templates do.
 */
export function wrapInRichControl(
  documentRoot: Element,
  written: string,
  control: { tag: string; alias: string; hint: string; id?: number },
): boolean {
  const body = find(documentRoot, "w:body");
  const paragraph = children(body).find(
    (child) => child.name === "w:p" && textOfParagraph(child).trim() === `{{${written}}}`,
  );
  if (!body || !paragraph) return false;
  const index = children(body).indexOf(paragraph);
  body.elements!.splice(
    index,
    1,
    element("w:sdt", {}, [
      element("w:sdtPr", {}, [
        element("w:alias", { "w:val": control.alias }),
        element("w:tag", { "w:val": control.tag }),
        element("w:id", { "w:val": control.id ?? 100_000 }),
        element("w:showingPlcHdr"),
      ]),
      element("w:sdtContent", {}, [
        element("w:p", {}, [element("w:r", {}, [wordText(control.hint)])]),
      ]),
    ]),
  );
  return true;
}

function textOfParagraph(paragraph: Element): string {
  let text = "";
  walk(paragraph, (node) => {
    if (node.name === "w:t")
      text += children(node)
        .filter((c) => c.type === "text")
        .map((c) => String(c.text ?? ""))
        .join("");
  });
  return text;
}
