import { afterEach, describe, expect, it } from "vitest";

import {
  clearComposerDraft,
  loadComposerDraft,
  saveComposerDraft
} from "./flowAIBuilderComposerDraft";

afterEach(() => {
  localStorage.clear();
});

describe("flowAIBuilderComposerDraft", () => {
  it("round-trips text and file references per session", () => {
    saveComposerDraft("s1", {
      text: "Lägg till en sammanfattning",
      files: [{ id: "f1", name: "underlag.pdf", size: 10, mimetype: "application/pdf" }]
    });
    expect(loadComposerDraft("s1")).toEqual({
      text: "Lägg till en sammanfattning",
      files: [{ id: "f1", name: "underlag.pdf", size: 10, mimetype: "application/pdf" }]
    });
    expect(loadComposerDraft("s2")).toBeNull();
  });

  it("removes the record when the draft becomes empty", () => {
    saveComposerDraft("s1", { text: "något", files: [] });
    saveComposerDraft("s1", { text: "", files: [] });
    expect(localStorage.getItem("eneo:ai-builder:draft:s1")).toBeNull();
  });

  it("tolerates corrupt or foreign payloads", () => {
    localStorage.setItem("eneo:ai-builder:draft:s1", "not json {");
    expect(loadComposerDraft("s1")).toBeNull();
    localStorage.setItem("eneo:ai-builder:draft:s1", JSON.stringify({ files: [{ bad: true }] }));
    expect(loadComposerDraft("s1")).toBeNull();
    localStorage.setItem(
      "eneo:ai-builder:draft:s1",
      JSON.stringify({ text: "ok", files: [{ bad: true }] })
    );
    expect(loadComposerDraft("s1")).toEqual({ text: "ok", files: [] });
  });

  it("clears explicitly", () => {
    saveComposerDraft("s1", { text: "något", files: [] });
    clearComposerDraft("s1");
    expect(loadComposerDraft("s1")).toBeNull();
  });
});
