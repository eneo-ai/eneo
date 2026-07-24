import type { OrganizationSkillSummaryPublic } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

const invalidate = vi.hoisted(() => vi.fn(async () => {}));

vi.mock("$app/navigation", () => ({
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  disableScrollHandling: vi.fn(),
  goto: vi.fn(),
  invalidate,
  invalidateAll: vi.fn(),
  onNavigate: vi.fn(),
  preloadCode: vi.fn(),
  preloadData: vi.fn(),
  pushState: vi.fn(),
  refreshAll: vi.fn(),
  replaceState: vi.fn()
}));

import OrganizationSkillsPage from "./+page.svelte";

function skill(
  id: string,
  publicationState: OrganizationSkillSummaryPublic["publication_state"],
  executionBlocked = false
): OrganizationSkillSummaryPublic {
  const revisionNumber = publicationState === "draft" ? 1 : 2;
  return {
    id,
    space_id: "organization-space",
    slug: id,
    is_active: publicationState === "published" || publicationState === "update_pending",
    current_revision_id: `${id}-revision-${revisionNumber}`,
    current_revision_number: revisionNumber,
    display_name: `${id} Skill`,
    description: `${id} description`,
    content_digest: id.repeat(64).slice(0, 64),
    created_by_user_id: "user-1",
    created_at: "2026-07-20T08:00:00Z",
    updated_at: "2026-07-20T09:00:00Z",
    published_revision_number: publicationState === "draft" ? null : 1,
    first_published_at: publicationState === "draft" ? null : "2026-07-19T08:00:00Z",
    publication_state: publicationState,
    execution_blocked: executionBlocked
  };
}

describe("organisation Skill catalogue page", () => {
  beforeEach(() => {
    invalidate.mockReset();
    invalidate.mockResolvedValue(undefined);
  });

  test("deletes only never-published drafts, then removes the deleted row", async () => {
    const draft = skill("draft", "draft");
    const unpublished = skill("unpublished", "unpublished");
    const published = skill("published", "published");
    const updatePending = skill("update-pending", "update_pending");
    const deleteSkill = vi.fn(async () => {});

    render(OrganizationSkillsPage, {
      data: {
        search: "",
        page: {
          items: [draft, unpublished, published, updatePending],
          count: 4,
          limit: 25,
          next_cursor: null
        },
        eneo: {
          skills: {
            organization: {
              delete: deleteSkill,
              list: vi.fn()
            },
            catalogue: {
              list: vi.fn()
            }
          }
        }
      } as never
    });

    await expect
      .element(
        page.getByRole("button", {
          name: m.skills_library_delete_aria({ name: draft.display_name })
        })
      )
      .toBeVisible();
    await expect
      .element(
        page.getByRole("button", {
          name: m.skills_library_delete_aria({ name: unpublished.display_name })
        })
      )
      .not.toBeInTheDocument();
    await expect
      .element(
        page.getByRole("button", {
          name: m.skills_library_delete_aria({ name: published.display_name })
        })
      )
      .not.toBeInTheDocument();
    await expect
      .element(
        page.getByRole("button", {
          name: m.skills_library_delete_aria({ name: updatePending.display_name })
        })
      )
      .not.toBeInTheDocument();

    await page
      .getByRole("button", {
        name: m.skills_library_delete_aria({ name: draft.display_name })
      })
      .click();
    await expect
      .element(
        page.getByText(
          m.organization_skills_delete_description({
            name: draft.display_name
          })
        )
      )
      .toBeVisible();
    await page.getByRole("button", { name: m.delete(), exact: true }).click();

    await vi.waitFor(() =>
      expect(deleteSkill).toHaveBeenCalledWith({
        skillId: draft.id
      })
    );
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("organization:skills"));
    await expect.element(page.getByText(draft.display_name)).not.toBeInTheDocument();
    await expect.element(page.getByText(unpublished.display_name)).toBeVisible();
  });

  test("shows execution blocking as the dominant operational status", async () => {
    const blocked = skill("blocked", "unpublished", true);

    render(OrganizationSkillsPage, {
      data: {
        search: "",
        page: {
          items: [blocked],
          count: 1,
          limit: 25,
          next_cursor: null
        },
        eneo: {
          skills: {
            organization: {
              delete: vi.fn(),
              list: vi.fn()
            },
            catalogue: {
              list: vi.fn()
            }
          }
        }
      } as never
    });

    await expect
      .element(page.getByText(m.organization_skills_status_blocked(), { exact: true }).first())
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_status_unpublished(), { exact: true }))
      .not.toBeInTheDocument();
  });

  test("keeps the catalogue table out of a second keyboard navigation region", async () => {
    const draft = skill("draft", "draft");

    render(OrganizationSkillsPage, {
      data: {
        search: "",
        page: {
          items: [draft],
          count: 1,
          limit: 25,
          next_cursor: null
        },
        eneo: {
          skills: {
            organization: {
              delete: vi.fn(),
              list: vi.fn()
            }
          }
        }
      } as never
    });

    const table = page.getByRole("table");
    await expect.element(table).toBeVisible();
    expect(table.element().closest('[role="region"]')).toBeNull();
  });

  test("keeps one action surface while catalogue fields adapt responsively", () => {
    const draft = skill("draft", "draft");

    render(OrganizationSkillsPage, {
      data: {
        search: "",
        page: {
          items: [draft],
          count: 1,
          limit: 25,
          next_cursor: null
        },
        eneo: {
          skills: {
            organization: {
              delete: vi.fn(),
              list: vi.fn()
            }
          }
        }
      } as never
    });

    expect(
      document.querySelectorAll(
        `[aria-label="${m.skills_library_delete_aria({ name: draft.display_name })}"]`
      )
    ).toHaveLength(1);
  });

  test("offers one clear creation action when the catalogue is empty", async () => {
    render(OrganizationSkillsPage, {
      data: {
        search: "",
        page: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        eneo: {
          skills: {
            organization: {
              delete: vi.fn(),
              list: vi.fn()
            },
            catalogue: {
              list: vi.fn()
            }
          }
        }
      } as never
    });

    await expect
      .element(page.getByRole("link", { name: m.skills_library_create_first() }))
      .toBeVisible();
    await expect
      .element(page.getByRole("link", { name: m.skills_library_create(), exact: true }))
      .not.toBeInTheDocument();
    await expect
      .element(page.getByRole("searchbox", { name: m.skills_library_search_placeholder() }))
      .not.toBeInTheDocument();
  });

  test("keeps a deleted Skill removed when refreshing the page data fails", async () => {
    const draft = skill("draft", "draft");
    const deleteSkill = vi.fn(async () => {});
    invalidate.mockRejectedValueOnce(new Error("Refresh failed"));

    render(OrganizationSkillsPage, {
      data: {
        search: "",
        page: {
          items: [draft],
          count: 1,
          limit: 25,
          next_cursor: null
        },
        eneo: {
          skills: {
            organization: {
              delete: deleteSkill,
              list: vi.fn()
            },
            catalogue: {
              list: vi.fn()
            }
          }
        }
      } as never
    });

    await page
      .getByRole("button", {
        name: m.skills_library_delete_aria({ name: draft.display_name })
      })
      .click();
    await page.getByRole("button", { name: m.delete(), exact: true }).click();

    await vi.waitFor(() => expect(deleteSkill).toHaveBeenCalledTimes(1));
    await expect.element(page.getByText(draft.display_name)).not.toBeInTheDocument();
    await expect
      .element(page.getByText(m.organization_skills_refresh_after_mutation_warning()))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_delete_error()))
      .not.toBeInTheDocument();
  });

  test("replaces appended results when the server page refreshes", async () => {
    const first = skill("first", "draft");
    const appended = skill("appended", "published");
    const refreshed = skill("refreshed", "published");
    const data = {
      search: "",
      page: {
        items: [first],
        count: 1,
        limit: 1,
        next_cursor: "next-page"
      },
      eneo: {
        skills: {
          organization: {
            delete: vi.fn(),
            list: vi.fn(async () => ({
              items: [appended],
              count: 1,
              limit: 1,
              next_cursor: null
            }))
          },
          catalogue: {
            list: vi.fn()
          }
        }
      }
    };
    const rendered = render(OrganizationSkillsPage, { data: data as never });

    await page.getByRole("button", { name: m.organization_skills_load_more() }).click();
    await expect.element(page.getByText(appended.display_name)).toBeVisible();

    await rendered.rerender({
      data: {
        ...data,
        page: {
          items: [refreshed],
          count: 1,
          limit: 1,
          next_cursor: null
        }
      } as never
    });

    await expect.element(page.getByText(refreshed.display_name)).toBeVisible();
    await expect.element(page.getByText(first.display_name)).not.toBeInTheDocument();
    await expect.element(page.getByText(appended.display_name)).not.toBeInTheDocument();
  });
});
