import { afterEach, describe, expect, it, vi } from "vitest";
import { createInstructionEditor, type InstructionEditor } from "@eneo/skill-instructions/editor";
import { serializeReference } from "@eneo/skill-instructions";

const target = { kind: "function", purpose: "web_search" } as const;
const token = serializeReference("Sök", target);
let editor: InstructionEditor;
let mount: HTMLDivElement;
afterEach(() => {
  editor?.destroy();
  mount?.remove();
});
function setup(value: string) {
  mount = document.createElement("div");
  document.body.append(mount);
  const onChange = vi.fn();
  const onReference = vi.fn();
  editor = createInstructionEditor({
    element: mount,
    value,
    id: "instructions",
    label: "Instructions",
    editorClass: "",
    referenceClass: "",
    onChange,
    onReference
  });
  return { onChange, onReference };
}
function key(key: string, options: KeyboardEventInit = {}) {
  mount
    .querySelector("[contenteditable]")!
    .dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...options })
    );
}

describe("literal instruction editor", () => {
  it("preserves whitespace, Unicode, examples and exact source through mode switches", () => {
    const text = "  ✨ Åäö é\n\n" + token + "\n\n`" + token + "`\n\t";
    const { onChange } = setup(text);
    expect(mount.querySelectorAll("button")).toHaveLength(1);
    expect(editor.getValue()).toBe(text);
    editor.setSource(true);
    expect(mount.querySelectorAll("button")).toHaveLength(0);
    editor.setSource(false);
    expect(editor.getValue()).toBe(text);
    expect(onChange.mock.calls.every(([value]) => value === text)).toBe(true);
  });
  it("inserts, replaces and removes each reference as one undo step", () => {
    setup("Skriv .");
    editor.replace({ ...editor.getSelection(), from: 6, to: 6 }, "Sök", target);
    expect(editor.getValue()).toBe("Skriv " + token + ".");
    key("z", { ctrlKey: true });
    expect(editor.getValue()).toBe("Skriv .");
    key("y", { ctrlKey: true });
    expect(editor.getValue()).toBe("Skriv " + token + ".");
    editor.replace({ ...editor.getSelection(), from: 6, to: 6 + token.length }, "Beräkna", {
      kind: "function",
      purpose: "compute"
    });
    expect(editor.getValue()).toContain("eneo-function:compute");
    key("z", { ctrlKey: true });
    expect(editor.getValue()).toBe("Skriv " + token + ".");
    editor.remove({ ...editor.getSelection(), from: 6, to: 6 + token.length });
    expect(editor.getValue()).toBe("Skriv .");
    key("z", { ctrlKey: true });
    expect(editor.getValue()).toBe("Skriv " + token + ".");
  });
  it.each(["replace", "remove"] as const)(
    "closes a pending picker after an edit and rejects its stale %s",
    (operation) => {
      const { onReference } = setup("Skriv " + token + ".");
      mount.querySelector("button")!.click();
      const pending = onReference.mock.lastCall![0];
      const changed = "En ny inledning. Skriv " + token + ".";
      editor.setValue(changed);
      expect(onReference).toHaveBeenLastCalledWith(null);
      if (operation === "replace")
        editor.replace(pending, "Beräkna", { kind: "function", purpose: "compute" });
      else editor.remove(pending);
      expect(editor.getValue()).toBe(changed);
    }
  );
  it("keeps undo after changing presentation and editing source", () => {
    setup("Skriv ");
    editor.replace({ ...editor.getSelection(), from: 6, to: 6 }, "Sök", target);
    editor.setSource(true);
    editor.setSource(false);
    key("z", { ctrlKey: true });
    expect(editor.getValue()).toBe("Skriv ");
  });
  it("keeps malformed reserved links visible and editable", () => {
    setup("[Name](eneo-skill:invalid)");
    expect(editor.getValue()).toBe("[Name](eneo-skill:invalid)");
    expect(mount.textContent).toContain("eneo-skill:invalid");
  });
  it("pastes literal text and references as one undo step without importing HTML", () => {
    setup("");
    editor.focus();
    const clipboard = new DataTransfer();
    clipboard.setData("text/plain", "  ✨ " + token + "\n");
    clipboard.setData("text/html", '<img src="https://example.invalid/image"><b>different</b>');
    mount.querySelector("[contenteditable]")!.dispatchEvent(
      new ClipboardEvent("paste", {
        clipboardData: clipboard,
        bubbles: true,
        cancelable: true
      })
    );
    expect(editor.getValue()).toBe("  ✨ " + token + "\n");
    expect(mount.querySelectorAll("button")).toHaveLength(1);
    expect(mount.querySelectorAll("img:not(.ProseMirror-separator), b")).toHaveLength(0);
    key("z", { ctrlKey: true });
    expect(editor.getValue()).toBe("");
  });
  it("does not open a reference picker during IME composition", () => {
    const { onReference } = setup("");
    editor.focus();
    const input = mount.querySelector("[contenteditable]")!;
    input.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true }));
    input.dispatchEvent(
      new KeyboardEvent("keypress", { key: "@", charCode: 64, bubbles: true, cancelable: true })
    );
    expect(onReference).not.toHaveBeenCalled();
    input.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true }));
  });
});
