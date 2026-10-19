import { get } from "svelte/store";
import { createEneo, type Space } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$app/paths", () => ({ resolve: (path: string) => path }));
vi.mock("$lib/core/errors", () => ({ toastError: vi.fn() }));

import { SpacesManager } from "./SpacesManager";

describe("SpacesManager.organizationSpaceId", () => {
  it("uses the current-space contract without needing organization membership and follows navigation", () => {
    const currentSpace = {
      id: "current",
      name: "Current space",
      description: null,
      personal: false,
      organization: false,
      organization_space_id: "org",
      embedding_models: [],
      completion_models: [],
      transcription_models: [],
      knowledge: {
        groups: { items: [], count: 0 },
        websites: { items: [], count: 0 },
        integration_knowledge_list: { items: [], count: 0 }
      },
      members: { items: [], count: 0 },
      group_members: { items: [], count: 0 },
      skill_permissions: [],
      available_roles: [],
      security_classification: null
    } satisfies Space;
    const m = SpacesManager({
      currentSpace,
      spaces: [],
      eneo: createEneo({ baseUrl: "https://eneo.invalid" })
    });

    expect(get(m.state.organizationSpaceId)).toBe("org");
    m.watchPageData({
      currentSpace: { ...currentSpace, id: "unlinked", organization_space_id: null }
    });
    expect(get(m.state.organizationSpaceId)).toBeNull();
  });
});
