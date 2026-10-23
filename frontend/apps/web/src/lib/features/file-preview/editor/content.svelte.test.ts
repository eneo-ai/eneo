import { Editor } from "@tiptap/core";
import { describe, expect, it, vi } from "vitest";
import { replaceContent } from "./content";
import { documentExtensions, withFinalNewline } from "./extensions";

const open = (markdown: string, editable = false) =>
  new Editor({
    element: document.createElement("div"),
    extensions: documentExtensions(),
    content: markdown,
    contentType: "markdown",
    editable
  });
const text = (editor: Editor) => withFinalNewline(editor.getMarkdown());

describe("replacing the document", () => {
  it("leaves nothing to undo once a draft has streamed in", () => {
    const editor = open("Ett\n");
    replaceContent(editor, "Ett två\n");
    replaceContent(editor, "Ett två tre\n");
    editor.setEditable(true, false);
    expect(editor.can().undo()).toBe(false);
    expect(text(editor)).toBe("Ett två tre\n");
    editor.destroy();
  });

  it("drops the reader's edits for good", () => {
    const editor = open("Ett\n", true);
    editor.commands.insertContentAt(4, " två");
    expect(text(editor)).toBe("Ett två\n");
    replaceContent(editor, "Ett\n");
    editor.commands.undo();
    expect(text(editor)).toBe("Ett\n");
    editor.destroy();
  });

  it("keeps what the reader types afterwards undoable", () => {
    const editor = open("Ett\n", true);
    replaceContent(editor, "Två\n");
    editor.commands.insertContentAt(4, " tre");
    expect(text(editor)).toBe("Två tre\n");
    editor.commands.undo();
    expect(text(editor)).toBe("Två\n");
    editor.destroy();
  });

  it("is no edit of the reader's", () => {
    const editor = open("Ett\n", true);
    const update = vi.fn();
    editor.on("update", update);
    replaceContent(editor, "Två\n");
    expect(update).not.toHaveBeenCalled();
    editor.destroy();
  });
});

describe("headings", () => {
  it("show at every level the Markdown has", () => {
    const editor = open("#### Fyra\n\n###### Sex\n");
    expect(editor.getHTML()).toBe("<h4>Fyra</h4><h6>Sex</h6>");
    editor.destroy();
  });
});
