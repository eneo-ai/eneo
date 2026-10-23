// Runs inside sandbox children only. The parsed-tree view of OOXML parts: the same xml-js
// element shape the docx library's patcher works on, so a part this module edits and a part
// patchDocument edits survive the round trip the same way. Nothing here touches XML as text.
import { js2xml, xml2js, type Element } from "xml-js";

export type { Element };

/** A part's root node: `elements` holds the declaration-less tree. */
export function parseXml(xml: string): Element {
  return xml2js(xml, { compact: false, captureSpacesBetweenElements: true }) as Element;
}

export function serializeXml(root: Element): string {
  return js2xml(root, { compact: false });
}

export const nameOf = (node: Element | undefined): string | undefined => node?.name;

export function attr(node: Element | undefined, name: string): string | undefined {
  const value = node?.attributes?.[name];
  return value === undefined ? undefined : String(value);
}

export function children(node: Element | undefined): Element[] {
  return node?.elements ?? [];
}

/** The first direct child with this name. */
export function find(node: Element | undefined, name: string): Element | undefined {
  return children(node).find((child) => child.type === "element" && child.name === name);
}

/** Every direct child with this name. */
export function findAll(node: Element | undefined, name: string): Element[] {
  return children(node).filter((child) => child.type === "element" && child.name === name);
}

/** The first element at this path of direct children, e.g. `["w:body", "w:sectPr"]`. */
export function at(node: Element | undefined, ...path: string[]): Element | undefined {
  let current = node;
  for (const name of path) current = find(current, name);
  return current;
}

/** The document element of a parsed part (the one child that is not the declaration). */
export function rootElement(part: Element): Element {
  const root = children(part).find((child) => child.type === "element");
  if (!root) throw new Error("The XML part has no root element.");
  return root;
}

/**
 * Walks the tree depth first. The visitor sees each element with its parent, and returns
 * false to skip the element's children.
 */
export function walk(
  node: Element,
  visit: (element: Element, parent: Element | undefined) => boolean | void,
  parent?: Element,
): void {
  if (node.type === "element" && visit(node, parent) === false) return;
  for (const child of children(node)) walk(child, visit, node);
}

/** The text of every `w:t` below the node, in document order. */
export function textOf(node: Element | undefined): string {
  if (!node) return "";
  let text = "";
  walk(node, (element) => {
    if (element.name === "w:t")
      text += children(element)
        .filter((child) => child.type === "text")
        .map((child) => String(child.text ?? ""))
        .join("");
    else if (element.name === "w:tab") text += "\t";
    else if (element.name === "w:br" || element.name === "w:cr") text += "\n";
  });
  return text;
}

export function element(
  name: string,
  attributes: Record<string, string | number> = {},
  elements: Element[] = [],
): Element {
  return { type: "element", name, attributes, elements };
}

export function textNode(text: string): Element {
  return { type: "text", text };
}

/** A `w:t` run text, preserving leading and trailing spaces. */
export function wordText(text: string): Element {
  return element("w:t", { "xml:space": "preserve" }, [textNode(text)]);
}

/** Removes `child` from `parent`, returning whether it was there. */
export function remove(parent: Element, child: Element): boolean {
  const index = children(parent).indexOf(child);
  if (index < 0) return false;
  parent.elements!.splice(index, 1);
  return true;
}

/** Replaces `child` within `parent` by `replacements`. */
export function replace(parent: Element, child: Element, replacements: Element[]): void {
  const index = children(parent).indexOf(child);
  if (index < 0) throw new Error("The element is not a child of the given parent.");
  parent.elements!.splice(index, 1, ...replacements);
}

/** Deep copy of a node. */
export function clone<T extends Element>(node: T): T {
  return structuredClone(node);
}
