import { EneoError, type OrganizationSkillSummaryPublic } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

/** ErrorCodes.SKILL_STILL_ATTACHED — the Skill is bound to a resource or policy. */
const SKILL_STILL_ATTACHED = 9051;

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
import { formatSkillUsage } from "$lib/features/skills/skillUsage";

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
    removed_at: null,
    usage: {
      assistant_count: 0,
      app_count: 0,
      distinct_space_count: 0,
      personal_chat_pinned: false
    },
    execution_blocked: executionBlocked
  };
}

describe("organisation Skill catalogue page", () => {
  beforeEach(() => {
    invalidate.mockReset();
    invalidate.mockResolvedValue(undefined);
  });

  test("removes an unused published skill after confirming retained history", async () => {
    const published = skill("published", "published");
    const unpublished = skill("unpublished", "unpublished");
    const removeMany = vi.fn(async () => ({ removed_ids: [published.id] }));
    render(OrganizationSkillsPage, {
      data: {
        search: "",
        removed: false,
        page: { items: [published, unpublished], count: 2, limit: 25, next_cursor: null },
        eneo: { skills: { organization: { removeMany, list: vi.fn() } } }
      } as never
    });

    for (const item of [published, unpublished]) {
      await expect
        .element(
          page.getByRole("button", {
            name: m.organization_skills_remove_aria({ name: item.display_name })
          })
        )
        .toBeVisible();
    }
    await page
      .getByRole("button", {
        name: m.organization_skills_remove_aria({ name: published.display_name })
      })
      .click();
    await expect.element(page.getByText(m.organization_skills_remove_description())).toBeVisible();
    await page
      .getByRole("button", { name: m.organization_skills_remove_action(), exact: true })
      .click();
    await vi.waitFor(() => expect(removeMany).toHaveBeenCalledWith({ skill_ids: [published.id] }));
    await expect
      .element(page.getByText(published.display_name, { exact: true }))
      .not.toBeInTheDocument();
    await expect.element(page.getByText(unpublished.display_name)).toBeVisible();
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("organization:skills"));
    await expect
      .element(
        page.getByRole("link", { name: m.organization_skills_current_filter(), exact: true })
      )
      .toHaveFocus();
  });

  test("names the attachment that blocks a delete instead of a model name clash", async () => {
    const draft = skill("draft", "draft");
    const deleteSkill = vi
      .fn()
      .mockRejectedValue(
        new EneoError(
          "This Skill is still attached. Remove every binding before deleting it.",
          "RESPONSE",
          409,
          SKILL_STILL_ATTACHED,
          { details: { skill_ids: [draft.id] } },
          { endpoint: "DELETE@/api/v1/skills/organization/" }
        )
      );

    render(OrganizationSkillsPage, {
      data: {
        search: "",
        page: { items: [draft], count: 1, limit: 25, next_cursor: null },
        eneo: {
          skills: {
            organization: { removeMany: deleteSkill, list: vi.fn() },
            catalogue: { list: vi.fn() }
          }
        }
      } as never
    });

    await page
      .getByRole("button", {
        name: m.organization_skills_remove_aria({ name: draft.display_name })
      })
      .click();
    await page
      .getByRole("button", { name: m.organization_skills_remove_action(), exact: true })
      .click();

    await expect.element(page.getByText(m.eneo_error_9051())).toBeVisible();
    await expect.element(page.getByText(m.organization_skills_remove_new_binding())).toBeVisible();
    await expect
      .element(
        page.getByRole("button", { name: m.organization_skills_remove_action(), exact: true })
      )
      .toBeDisabled();
    // The shared collision code this conflict used to travel under is generic,
    // but its localized copy is about AI model display names.
    await expect.element(page.getByText(m.eneo_error_9017())).not.toBeInTheDocument();
    await expect
      .element(page.getByRole("link", { name: draft.display_name }).first())
      .toBeVisible();
  });

  test("bulk removal requires excluding skills in use and preserves the reviewed selection", async () => {
    const free = skill("free", "published");
    const used = {
      ...skill("used", "published"),
      usage: {
        assistant_count: 2,
        app_count: 1,
        distinct_space_count: 2,
        personal_chat_pinned: true
      }
    };
    const removeMany = vi.fn(async () => ({ removed_ids: [free.id] }));
    render(OrganizationSkillsPage, {
      data: {
        search: "",
        removed: false,
        page: { items: [free, used], count: 2, limit: 25, next_cursor: null },
        eneo: { skills: { organization: { removeMany, list: vi.fn() } } }
      } as never
    });
    await expect
      .element(
        page.getByRole("link", {
          name: new RegExp(formatSkillUsage(used.usage) ?? "")
        })
      )
      .toBeVisible();
    await page
      .getByRole("checkbox", { name: m.organization_skills_select_shown({ count: "2" }) })
      .click();
    await page.getByRole("button", { name: m.organization_skills_remove_selected() }).click();
    await expect
      .element(page.getByText(m.organization_skills_remove_blocked_title()))
      .toBeVisible();
    await expect
      .element(
        page.getByRole("button", {
          name: m.organization_skills_remove_confirm({ count: "2" }),
          exact: true
        })
      )
      .toBeDisabled();
    expect(removeMany).not.toHaveBeenCalled();
    await page
      .getByRole("button", { name: m.organization_skills_remove_exclude_blocked({ count: "1" }) })
      .click();
    await page
      .getByRole("button", { name: m.organization_skills_remove_action(), exact: true })
      .click();
    await vi.waitFor(() => expect(removeMany).toHaveBeenCalledWith({ skill_ids: [free.id] }));
    await expect.element(page.getByText(used.display_name)).toBeVisible();
    await expect.element(page.getByText(free.display_name)).not.toBeInTheDocument();
  });

  test("removed view retains history links and search scope without selection or removal actions", async () => {
    const removed = { ...skill("removed", "unpublished"), removed_at: "2026-09-18T08:00:00Z" };
    render(OrganizationSkillsPage, {
      data: {
        search: "Payroll",
        removed: true,
        page: { items: [removed], count: 1, limit: 25, next_cursor: null },
        eneo: { skills: { organization: { removeMany: vi.fn(), list: vi.fn() } } }
      } as never
    });
    await expect.element(page.getByRole("link", { name: removed.display_name })).toBeVisible();
    await expect.element(page.getByRole("checkbox")).not.toBeInTheDocument();
    await expect
      .element(
        page.getByRole("button", {
          name: m.organization_skills_remove_aria({ name: removed.display_name })
        })
      )
      .not.toBeInTheDocument();
    expect(document.querySelector<HTMLInputElement>('input[name="removed"]')?.value).toBe("true");
    await expect
      .element(
        page.getByRole("link", { name: m.organization_skills_removed_filter(), exact: true })
      )
      .toHaveAttribute("aria-current", "page");
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
        `[aria-label="${m.organization_skills_remove_aria({ name: draft.display_name })}"]`
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
    const deleteSkill = vi.fn(async () => ({ removed_ids: [draft.id] }));
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
              removeMany: deleteSkill,
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
        name: m.organization_skills_remove_aria({ name: draft.display_name })
      })
      .click();
    await page
      .getByRole("button", { name: m.organization_skills_remove_action(), exact: true })
      .click();

    await vi.waitFor(() => expect(deleteSkill).toHaveBeenCalledTimes(1));
    await expect.element(page.getByText(draft.display_name)).not.toBeInTheDocument();
    await expect
      .element(page.getByText(m.organization_skills_refresh_after_mutation_warning()))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_remove_error()))
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
