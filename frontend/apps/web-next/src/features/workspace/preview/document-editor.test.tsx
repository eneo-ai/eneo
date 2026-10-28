// @vitest-environment jsdom
import { act, cleanup, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { DocumentEditor, type DocumentEditorHandle } from "./document-editor";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(() => {
  cleanup();
});

const MARKDOWN = "# Plan\n\nMötet hålls på måndag.\n\n- [ ] Boka rum\n";

it("lays out the document, says so, and hands back its Markdown", async () => {
  const ref = createRef<DocumentEditorHandle>();
  const onReady = vi.fn();
  renderInApp(<DocumentEditor ref={ref} markdown={MARKDOWN} onReady={onReady} />);

  await vi.waitFor(() =>
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Plan")
  );
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
  expect(onReady).toHaveBeenCalledTimes(1);
  expect(ref.current?.getMarkdown()).toBe(MARKDOWN);
});

it("marks a passage it is asked to point out, and what changed against the previous version", async () => {
  const view = renderInApp(
    <DocumentEditor
      markdown={MARKDOWN}
      highlight={{ text: "Boka rum", locator: null }}
      previousMarkdown={"# Plan\n\nMötet hålls på fredag.\n\n- [ ] Boka rum\n"}
    />
  );

  const marked = (selector: string) => view.container.querySelector(selector)?.textContent;
  await vi.waitFor(() => expect(marked(".passage-highlight")).toBe("Boka rum"));
  expect(marked(".change-added")).toBe("måndag");
  expect(marked(".change-removed")).toBe("fredag");
});

it("takes new Markdown once laid out, and shows the file's text again on reset", async () => {
  const ref = createRef<DocumentEditorHandle>();
  const onRender = vi.fn();
  const view = renderInApp(<DocumentEditor ref={ref} markdown={"Första.\n"} onRender={onRender} />);
  await vi.waitFor(() => expect(onRender).toHaveBeenCalledTimes(1));

  view.rerender(<DocumentEditor ref={ref} markdown={"Andra.\n"} onRender={onRender} />);
  await vi.waitFor(() => expect(onRender).toHaveBeenCalledTimes(2));
  expect(ref.current?.getMarkdown()).toBe("Andra.\n");

  await act(async () => ref.current?.reset());
  expect(ref.current?.getMarkdown()).toBe("Andra.\n");
});

it("does not count the editor's own tidying of a loaded document as an edit", async () => {
  // A table's columns come back padded, so the file's Markdown is not what
  // the editor serialises; the text still says the same.
  const table = "| a | bb |\n| --- | --- |\n| 1 | 2 |\n";
  const ref = createRef<DocumentEditorHandle>();
  const onChange = vi.fn();
  const onRender = vi.fn();
  const view = renderInApp(
    <DocumentEditor ref={ref} markdown={table} editable onChange={onChange} onRender={onRender} />
  );
  await vi.waitFor(() => expect(onRender).toHaveBeenCalledTimes(1));
  expect(ref.current?.getMarkdown()).not.toBe(table);

  view.rerender(
    <DocumentEditor
      ref={ref}
      markdown={`${table}\nSlut.\n`}
      editable
      onChange={onChange}
      onRender={onRender}
    />
  );
  await vi.waitFor(() => expect(onRender).toHaveBeenCalledTimes(2));

  expect(onChange).not.toHaveBeenCalled();
});

it("shows edits an earlier editor left, still unsaved", async () => {
  const ref = createRef<DocumentEditorHandle>();
  const onChange = vi.fn();
  const onRender = vi.fn();
  renderInApp(
    <DocumentEditor
      ref={ref}
      markdown={MARKDOWN}
      edits={"# Plan\n\nMötet hålls på tisdag.\n"}
      editable
      onChange={onChange}
      onRender={onRender}
    />
  );
  await vi.waitFor(() => expect(onRender).toHaveBeenCalledTimes(1));

  expect(ref.current?.getMarkdown()).toBe("# Plan\n\nMötet hålls på tisdag.\n");
  // Still the reader's unsaved text: the panel knows, so it is not told again.
  expect(onChange).not.toHaveBeenCalled();

  await act(async () => ref.current?.reset());
  expect(ref.current?.getMarkdown()).toBe(MARKDOWN);
});
