import { cleanup, render, screen } from "@testing-library/svelte";
import type { GroupSparse, UploadedFile, WebsiteSparse } from "@eneo/eneo-js";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

import FlowStepContextSection from "./FlowStepContextSection.svelte";
import { readable } from "svelte/store";

// SelectKnowledge needs the full space context tree; the published/draft
// mutator contract under test does not depend on its internals.
vi.mock("$lib/features/knowledge/components/select/SelectKnowledge.svelte", async () => {
  const Stub = (await import("./test-harnesses/EmptyStub.svelte")).default;
  return { default: Stub };
});

vi.mock("$lib/features/attachments/AttachmentManager", () => ({
  getAttachmentManager: () => ({
    state: { attachmentRules: readable({}) },
    queueValidUploads: vi.fn()
  })
}));

vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: {
      currentSpace: readable({
        id: "space-1",
        embedding_models: [],
        knowledge: { websites: [], groups: [], integrationKnowledge: [] }
      }),
      organizationSpaceId: readable(null)
    },
    refreshCurrentSpace: vi.fn()
  })
}));

const attachment: Pick<UploadedFile, "id" | "name" | "mimetype" | "size"> = {
  id: "file-1",
  name: "underlag.pdf",
  mimetype: "application/pdf",
  size: 12345
};

const group: Pick<GroupSparse, "id" | "name"> & {
  metadata: { num_info_blobs: number };
} = {
  id: "group-1",
  name: "Handläggningsstöd",
  metadata: { num_info_blobs: 3 }
};

const unnamedWebsite: Pick<WebsiteSparse, "id" | "url"> & { name: null } = {
  id: "website-1",
  url: "https://www.sundsvall.se/handlaggning",
  name: null
};

function renderSection(isPublished: boolean, onKnowledgeChange = vi.fn()) {
  render(FlowStepContextSection, {
    props: {
      assistant: {
        id: "assistant-1",
        websites: [unnamedWebsite as WebsiteSparse],
        groups: [group as GroupSparse],
        integration_knowledge_list: [],
        attachments: [attachment as UploadedFile]
      },
      assistantLoading: false,
      runningUploads: [
        {
          id: "upload-1",
          file: new File(["x"], "pågående.pdf", { type: "application/pdf" }),
          status: "uploading",
          progress: 40,
          remove: vi.fn()
        }
      ],
      isPublished,
      onKnowledgeChange
    }
  });
  return onKnowledgeChange;
}

afterEach(() => {
  cleanup();
});

describe("FlowStepContextSection published mode", () => {
  it("keeps knowledge and attachments readable while no mutator renders", () => {
    renderSection(true);

    expect(screen.getByText("Handläggningsstöd")).toBeTruthy();
    // Unnamed websites use the canonical shortened-URL label, never a blank
    // row or a UUID.
    expect(screen.getByText("www.sundsvall.se/handlaggning")).toBeTruthy();
    expect(screen.getByText("underlag.pdf")).toBeTruthy();

    expect(screen.queryAllByTestId("select-knowledge-stub")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: m.remove() })).toBeNull();
    expect(screen.queryByText(m.upload_attachment())).toBeNull();
    expect(screen.queryByRole("button", { name: m.cancel() })).toBeNull();
  });

  it("offers every mutator on an editable draft", () => {
    renderSection(false);

    expect(screen.queryAllByTestId("select-knowledge-stub")).toHaveLength(2);
    expect(screen.getByRole("button", { name: m.remove() })).toBeTruthy();
    expect(screen.getByText(m.upload_attachment())).toBeTruthy();
    expect(screen.getByRole("button", { name: m.cancel() })).toBeTruthy();
  });
});
