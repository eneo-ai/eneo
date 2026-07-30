import {
  type AssistantFleetAdvancePublic,
  EneoError,
  type OrganizationSkillPublic,
  type PublishedSkillPublic,
  type SkillExecutionBlockState,
  type SkillRevisionPublic
} from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { SKILL_EXECUTION_BLOCK_CONFLICT } from "$lib/core/errors";
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

import OrganizationSkillDetailPage from "./+page.svelte";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function revision(revisionNumber: number): SkillRevisionPublic {
  return {
    id: `revision-${revisionNumber}`,
    skill_id: "skill-1",
    revision_number: revisionNumber,
    display_name: "HR support",
    description: `Revision ${revisionNumber}`,
    instructions: `Follow revision ${revisionNumber}.`,
    content_digest: String(revisionNumber).repeat(64),
    created_by_user_id: "user-1",
    created_at: `2026-07-${18 + revisionNumber}T08:00:00Z`
  };
}

function updatePendingSkill(): OrganizationSkillPublic {
  const currentRevision = revision(2);
  return {
    id: "skill-1",
    space_id: "organization-space",
    slug: "hr-support",
    is_active: true,
    current_revision_id: currentRevision.id,
    current_revision_number: currentRevision.revision_number,
    display_name: currentRevision.display_name,
    description: currentRevision.description,
    content_digest: currentRevision.content_digest,
    created_by_user_id: "user-1",
    created_at: "2026-07-19T08:00:00Z",
    updated_at: "2026-07-20T08:00:00Z",
    published_revision_number: 1,
    first_published_at: "2026-07-19T09:00:00Z",
    publication_state: "update_pending",
    execution_blocked: false,
    current_revision: currentRevision
  };
}

function publishedSkill(): PublishedSkillPublic {
  const publishedRevision = revision(1);
  return {
    id: "skill-1",
    slug: "hr-support",
    revision_id: publishedRevision.id,
    revision_number: publishedRevision.revision_number,
    display_name: publishedRevision.display_name,
    description: publishedRevision.description,
    content_digest: publishedRevision.content_digest,
    first_published_at: "2026-07-19T09:00:00Z",
    execution_blocked: false,
    revision: publishedRevision
  };
}

function adoptionPage() {
  return {
    summary: {
      assistant_count: 0,
      app_count: 0,
      distinct_space_count: 0,
      behind_published_count: 0,
      personal_chat: null,
      revision_counts: []
    },
    items: [],
    limit: 25,
    next_cursor: null
  };
}

function unblockedState(): SkillExecutionBlockState {
  return {
    skill_id: "skill-1",
    block: null
  };
}

function publicationLifecycleData({
  skill = updatePendingSkill(),
  adoption = Promise.resolve(adoptionPage()),
  advanceAssistants = vi.fn(),
  advancePersonalChat = vi.fn(),
  getAdoption = vi.fn(),
  publish = vi.fn(async () => {})
}: {
  skill?: OrganizationSkillPublic;
  adoption?: Promise<unknown>;
  advanceAssistants?: unknown;
  advancePersonalChat?: unknown;
  getAdoption?: unknown;
  publish?: unknown;
} = {}) {
  return {
    skill,
    published: publishedSkill(),
    revisionPage: {
      items: [],
      count: 0,
      limit: 25,
      next_cursor: null
    },
    adoptionPage: adoption,
    executionBlock: { ...unblockedState(), skill_id: skill.id },
    eneo: {
      settings: {
        blockSkillExecution: vi.fn(),
        getSkillExecutionBlock: vi.fn(),
        unblockSkillExecution: vi.fn()
      },
      skills: {
        organization: {
          advanceAssistants,
          advancePersonalChat,
          createRevision: vi.fn(),
          getAdoption,
          getRevision: vi.fn(),
          listRevisionSummaries: vi.fn(),
          publish,
          restoreRevision: vi.fn(),
          unpublish: vi.fn()
        }
      }
    }
  };
}

function deferredAdvance() {
  let resolve!: (value: {
    outcome: "advanced";
    from_revision_number: number;
    to_revision_number: number;
  }) => void;
  const promise = new Promise<{
    outcome: "advanced";
    from_revision_number: number;
    to_revision_number: number;
  }>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("organisation Skill detail page", () => {
  beforeEach(() => {
    invalidate.mockReset();
    invalidate.mockResolvedValue(undefined);
  });

  test("keeps a created revision saved when refreshing the page data fails", async () => {
    const createRevision = vi.fn(async () => {});
    invalidate.mockRejectedValueOnce(new Error("Refresh failed"));

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              createRevision,
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page.getByLabelText(m.skills_description_label()).fill("Updated description");
    await page.getByRole("button", { name: m.save(), exact: true }).click();

    await vi.waitFor(() =>
      expect(createRevision).toHaveBeenCalledWith({
        skillId: "skill-1",
        display_name: "HR support",
        description: "Updated description",
        instructions: "Follow revision 2."
      })
    );
    await expect
      .element(page.getByRole("status").getByText(m.skills_form_saved_status(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_refresh_after_mutation_warning()))
      .toBeVisible();
    await expect
      .element(page.getByText(m.skills_revision_form_error_title()))
      .not.toBeInTheDocument();
    expect(createRevision).toHaveBeenCalledTimes(1);
  });

  test("moves the Personal Chat binding through the reviewed pin and refreshes", async () => {
    const advancePersonalChat = vi.fn(async () => ({
      outcome: "advanced" as const,
      from_revision_number: 1,
      to_revision_number: 2
    }));
    const skill = {
      ...updatePendingSkill(),
      published_revision_number: 2,
      publication_state: "published" as const
    };
    const published = {
      ...publishedSkill(),
      revision_id: "revision-2",
      revision_number: 2
    };
    const behindAdoption = {
      ...adoptionPage(),
      summary: {
        ...adoptionPage().summary,
        personal_chat: {
          revision_id: "revision-1",
          revision_number: 1,
          drift: "behind" as const
        }
      }
    };
    render(OrganizationSkillDetailPage, {
      data: {
        skill,
        published,
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(behindAdoption),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              advancePersonalChat,
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              get: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page
      .getByRole("button", {
        name: m.organization_skills_adoption_personal_chat_advance_action()
      })
      .click();
    await expect
      .element(
        page.getByText(m.organization_skills_advance_description({ pinned: "1", published: "2" }))
      )
      .toBeVisible();
    await page.getByRole("button", { name: m.organization_skills_advance_confirm() }).click();

    await vi.waitFor(() =>
      expect(advancePersonalChat).toHaveBeenCalledWith({
        skillId: "skill-1",
        expected_pinned_revision_id: "revision-1",
        expected_published_revision_id: "revision-2"
      })
    );
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("organization:skills"));
    await expect
      .element(page.getByText(m.organization_skills_advance_title()))
      .not.toBeInTheDocument();
    await expect
      .element(page.getByText(m.organization_skills_advance_announcement({ version: "2" })))
      .toBeInTheDocument();
  });

  test("a retried adoption load still offers the Personal Chat update", async () => {
    const advancePersonalChat = vi.fn(async () => ({
      outcome: "advanced" as const,
      from_revision_number: 1,
      to_revision_number: 2
    }));
    const skill = {
      ...updatePendingSkill(),
      published_revision_number: 2,
      publication_state: "published" as const
    };
    const published = {
      ...publishedSkill(),
      revision_id: "revision-2",
      revision_number: 2
    };
    const behindAdoption = {
      ...adoptionPage(),
      summary: {
        ...adoptionPage().summary,
        personal_chat: {
          revision_id: "revision-1",
          revision_number: 1,
          drift: "behind" as const
        }
      }
    };
    const getAdoption = vi.fn(async () => behindAdoption);
    render(OrganizationSkillDetailPage, {
      data: {
        skill,
        published,
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.reject(new Error("Transient adoption failure")),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              advancePersonalChat,
              createRevision: vi.fn(),
              getAdoption,
              get: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await expect
      .element(page.getByText(m.organization_skills_adoption_error_title()))
      .toBeVisible();
    await page.getByRole("button", { name: m.retry() }).click();
    await page
      .getByRole("button", {
        name: m.organization_skills_adoption_personal_chat_advance_action()
      })
      .click();
    await page.getByRole("button", { name: m.organization_skills_advance_confirm() }).click();

    await vi.waitFor(() =>
      expect(advancePersonalChat).toHaveBeenCalledWith({
        skillId: "skill-1",
        expected_pinned_revision_id: "revision-1",
        expected_published_revision_id: "revision-2"
      })
    );
  });

  test("navigating to another Skill discards the reviewed update state", async () => {
    const firstAdvance = deferredAdvance();
    const advancePersonalChat = vi.fn(() => firstAdvance.promise);
    const skill = {
      ...updatePendingSkill(),
      published_revision_number: 2,
      publication_state: "published" as const
    };
    const published = {
      ...publishedSkill(),
      revision_id: "revision-2",
      revision_number: 2
    };
    const behindAdoption = {
      ...adoptionPage(),
      summary: {
        ...adoptionPage().summary,
        personal_chat: {
          revision_id: "revision-1",
          revision_number: 1,
          drift: "behind" as const
        }
      }
    };
    const dataFor = (skillId: string) =>
      ({
        skill: { ...skill, id: skillId },
        published,
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(behindAdoption),
        executionBlock: { skill_id: skillId, block: null },
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              advancePersonalChat,
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              get: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      }) as never;
    const rendered = render(OrganizationSkillDetailPage, { data: dataFor("skill-1") });

    // Submit for Skill A, then navigate to Skill B while the request runs.
    await page
      .getByRole("button", {
        name: m.organization_skills_adoption_personal_chat_advance_action()
      })
      .click();
    await page.getByRole("button", { name: m.organization_skills_advance_confirm() }).click();
    await vi.waitFor(() =>
      expect(advancePersonalChat).toHaveBeenCalledWith({
        skillId: "skill-1",
        expected_pinned_revision_id: "revision-1",
        expected_published_revision_id: "revision-2"
      })
    );

    await rendered.rerender({ data: dataFor("skill-2") });
    await expect
      .element(page.getByText(m.organization_skills_advance_title()))
      .not.toBeInTheDocument();

    firstAdvance.resolve({
      outcome: "advanced",
      from_revision_number: 1,
      to_revision_number: 2
    });
    await expect
      .element(page.getByText(m.organization_skills_advance_announcement({ version: "2" })))
      .not.toBeInTheDocument();
    expect(invalidate).not.toHaveBeenCalled();
    // The dialog opened for Skill B must review Skill B, not replay Skill A.
    await page
      .getByRole("button", {
        name: m.organization_skills_adoption_personal_chat_advance_action()
      })
      .click();
    await page.getByRole("button", { name: m.organization_skills_advance_confirm() }).click();
    await vi.waitFor(() =>
      expect(advancePersonalChat).toHaveBeenLastCalledWith({
        skillId: "skill-2",
        expected_pinned_revision_id: "revision-1",
        expected_published_revision_id: "revision-2"
      })
    );
  });

  test("keeps the update dialog open with the error when the move is refused", async () => {
    const advancePersonalChat = vi.fn(async () => {
      throw new Error("Refused");
    });
    const skill = {
      ...updatePendingSkill(),
      published_revision_number: 2,
      publication_state: "published" as const
    };
    const published = {
      ...publishedSkill(),
      revision_id: "revision-2",
      revision_number: 2
    };
    const behindAdoption = {
      ...adoptionPage(),
      summary: {
        ...adoptionPage().summary,
        personal_chat: {
          revision_id: "revision-1",
          revision_number: 1,
          drift: "behind" as const
        }
      }
    };
    render(OrganizationSkillDetailPage, {
      data: {
        skill,
        published,
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(behindAdoption),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              advancePersonalChat,
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              get: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page
      .getByRole("button", {
        name: m.organization_skills_adoption_personal_chat_advance_action()
      })
      .click();
    await page.getByRole("button", { name: m.organization_skills_advance_confirm() }).click();

    await expect.element(page.getByText(m.organization_skills_advance_error())).toBeVisible();
    await expect.element(page.getByText(m.organization_skills_advance_title())).toBeVisible();
    expect(invalidate).not.toHaveBeenCalled();
  });

  test("hides the approved snapshot when it matches the current revision", async () => {
    const skill = {
      ...updatePendingSkill(),
      published_revision_number: 2,
      publication_state: "published" as const
    };
    render(OrganizationSkillDetailPage, {
      data: {
        skill,
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              get: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await expect
      .element(page.getByRole("heading", { name: m.skills_library_content_heading() }))
      .toBeVisible();
    expect(document.querySelector("#organization-skill-approved-heading")).toBeNull();
  });

  test("places adoption oversight after publication and before revision history", async () => {
    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              get: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    const content = document
      .querySelector("#organization-skill-content-heading")
      ?.closest("section");
    const approved = document
      .querySelector("#organization-skill-approved-heading")
      ?.closest("section");
    const publication = document.querySelector("aside[aria-labelledby]");
    await expect
      .element(
        page.getByRole("heading", {
          name: m.organization_skills_adoption_heading()
        })
      )
      .toBeVisible();
    const adoption = document
      .querySelector("#organization-skill-adoption-heading")
      ?.closest("section");
    const history = document
      .querySelector("#organization-skill-history-heading")
      ?.closest("section");

    expect(content).not.toBeNull();
    expect(approved).not.toBeNull();
    expect(publication).not.toBeNull();
    expect(adoption).not.toBeNull();
    expect(history).not.toBeNull();
    expect(content?.compareDocumentPosition(approved as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(approved?.compareDocumentPosition(publication as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(publication?.compareDocumentPosition(adoption as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(adoption?.compareDocumentPosition(history as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

  test("unpublishes an approved revision while a newer draft remains pending", async () => {
    const publish = vi.fn(async () => {});
    const unpublish = vi.fn(async () => {});

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish,
              restoreRevision: vi.fn(),
              unpublish
            }
          }
        }
      } as never
    });

    await expect
      .element(page.getByRole("button", { name: m.organization_skills_publish_update_action() }))
      .toBeVisible();
    await page
      .getByRole("button", { name: m.organization_skills_unpublish_action(), exact: true })
      .click();
    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_unpublish_title() }))
      .toBeVisible();

    await page
      .getByRole("button", { name: m.organization_skills_unpublish_action(), exact: true })
      .last()
      .click();

    await vi.waitFor(() =>
      expect(unpublish).toHaveBeenCalledWith({
        skillId: "skill-1"
      })
    );
    expect(publish).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("organization:skills"));
  });

  test("offers binding updates only for publish and respects an unchecked choice", async () => {
    const pendingPublish = deferred<void>();
    const publish = vi.fn(() => pendingPublish.promise);
    const advancePersonalChat = vi.fn();
    const advanceAssistants = vi.fn();

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              advanceAssistants,
              advancePersonalChat,
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish,
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    const updateBindings = page.getByRole("checkbox", {
      name: m.organization_skills_publish_update_bindings_label()
    });
    await expect.element(updateBindings).toBeChecked();
    await expect
      .element(page.getByText(m.organization_skills_publish_update_bindings_description()))
      .toBeVisible();
    await updateBindings.click();
    await expect.element(updateBindings).not.toBeChecked();
    await page.getByRole("button", { name: m.cancel() }).click();
    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    await expect.element(updateBindings).toBeChecked();
    await updateBindings.click();

    await page
      .getByRole("button", { name: m.organization_skills_publish_action(), exact: true })
      .last()
      .click();
    await expect.element(updateBindings).toBeDisabled();
    pendingPublish.resolve(undefined);

    await vi.waitFor(() =>
      expect(publish).toHaveBeenCalledWith({
        skillId: "skill-1",
        expected_revision_id: "revision-2"
      })
    );
    expect(advancePersonalChat).not.toHaveBeenCalled();
    expect(advanceAssistants).not.toHaveBeenCalled();

    await page
      .getByRole("button", { name: m.organization_skills_unpublish_action(), exact: true })
      .click();
    await expect
      .element(
        page.getByRole("checkbox", {
          name: m.organization_skills_publish_update_bindings_label()
        })
      )
      .not.toBeInTheDocument();
  });

  test("updates reviewed bindings across Assistant chunks and shows the aggregate receipt", async () => {
    const secondChunk = deferred<AssistantFleetAdvancePublic>();
    const personalChatAdvance = deferred<{
      outcome: "advanced";
      from_revision_number: number;
      to_revision_number: number;
    }>();
    const publish = vi.fn(async () => {});
    const advancePersonalChat = vi.fn(() => personalChatAdvance.promise);
    const advanceAssistants = vi
      .fn()
      .mockResolvedValueOnce({
        run_id: "run-1",
        next_cursor: "cursor-2",
        counts: {
          advanced: 1,
          concurrent_change: 1,
          incompatible: 1
        },
        outcomes: [
          { assistant_id: "assistant-1", outcome: "advanced" },
          { assistant_id: "assistant-2", outcome: "concurrent_change" },
          {
            assistant_id: "assistant-3",
            outcome: "incompatible",
            reason: "activation_unavailable"
          }
        ]
      })
      .mockReturnValueOnce(secondChunk.promise);
    const reviewedAdoption = {
      ...adoptionPage(),
      summary: {
        assistant_count: 5,
        app_count: 1,
        distinct_space_count: 2,
        behind_published_count: 5,
        personal_chat: {
          revision_id: "revision-1",
          revision_number: 1,
          drift: "behind" as const
        },
        revision_counts: [
          {
            revision_id: "revision-1",
            revision_number: 1,
            assistant_count: 4,
            app_count: 1,
            personal_chat_pinned: true
          },
          {
            revision_id: "revision-2",
            revision_number: 2,
            assistant_count: 1,
            app_count: 0,
            personal_chat_pinned: false
          }
        ]
      }
    };

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(reviewedAdoption),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              advanceAssistants,
              advancePersonalChat,
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish,
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    await page
      .getByRole("button", { name: m.organization_skills_publish_action(), exact: true })
      .last()
      .click();

    await expect
      .element(page.getByText(m.organization_skills_rollout_status_running(), { exact: true }))
      .toBeVisible();
    await vi.waitFor(() => expect(advanceAssistants).toHaveBeenCalledTimes(2));
    expect(publish).toHaveBeenCalledWith({
      skillId: "skill-1",
      expected_revision_id: "revision-2"
    });
    expect(advancePersonalChat).toHaveBeenCalledWith({
      skillId: "skill-1",
      expected_pinned_revision_id: "revision-1",
      expected_published_revision_id: "revision-2"
    });
    expect(advanceAssistants).toHaveBeenNthCalledWith(1, {
      skillId: "skill-1",
      expected_published_revision_id: "revision-2",
      cursor: null
    });
    expect(advanceAssistants).toHaveBeenNthCalledWith(2, {
      skillId: "skill-1",
      expected_published_revision_id: "revision-2",
      cursor: "cursor-2"
    });

    secondChunk.resolve({
      run_id: "run-1",
      next_cursor: null,
      counts: {
        advanced: 1,
        concurrent_change: 0,
        incompatible: 1
      },
      outcomes: [
        { assistant_id: "assistant-4", outcome: "advanced" },
        {
          assistant_id: "assistant-5",
          outcome: "incompatible",
          reason: "context_window"
        }
      ]
    });

    await expect
      .element(page.getByText(m.organization_skills_rollout_status_running(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_personal_chat_pending()))
      .toBeVisible();

    personalChatAdvance.resolve({
      outcome: "advanced",
      from_revision_number: 1,
      to_revision_number: 2
    });

    await expect
      .element(page.getByText(m.organization_skills_rollout_status_completed(), { exact: true }))
      .toBeVisible();
    await expect
      .element(
        page.getByText(
          m.organization_skills_rollout_progress({
            updated: "2",
            total: "5"
          })
        )
      )
      .toBeVisible();
    await expect
      .element(
        page.getByRole("row", {
          name: `${m.organization_skills_rollout_concurrent_change()} 1`
        })
      )
      .toBeVisible();
    await expect
      .element(
        page.getByRole("row", {
          name: `${m.organization_skills_rollout_activation_unavailable()} 1`
        })
      )
      .toBeVisible();
    await expect
      .element(
        page.getByRole("row", {
          name: `${m.organization_skills_rollout_context_window()} 1`
        })
      )
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_personal_chat_advanced()))
      .toBeVisible();
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("organization:skills"));
  });

  test("continues publication and the Assistant walk when adoption could not be read", async () => {
    const publish = vi.fn(async () => {});
    const getAdoption = vi.fn(async () => {
      throw new Error("Adoption unavailable");
    });
    const advancePersonalChat = vi.fn();
    const advanceAssistants = vi.fn(async () => ({
      run_id: "run-1",
      next_cursor: null,
      counts: {
        advanced: 0,
        concurrent_change: 0,
        incompatible: 0
      },
      outcomes: []
    }));

    render(OrganizationSkillDetailPage, {
      data: publicationLifecycleData({
        adoption: Promise.reject(new Error("Adoption unavailable")),
        advanceAssistants,
        advancePersonalChat,
        getAdoption,
        publish
      }) as never
    });

    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    await page
      .getByRole("button", { name: m.organization_skills_publish_action(), exact: true })
      .last()
      .click();

    await vi.waitFor(() =>
      expect(publish).toHaveBeenCalledWith({
        skillId: "skill-1",
        expected_revision_id: "revision-2"
      })
    );
    await vi.waitFor(() =>
      expect(advanceAssistants).toHaveBeenCalledWith({
        skillId: "skill-1",
        expected_published_revision_id: "revision-2",
        cursor: null
      })
    );
    expect(getAdoption).toHaveBeenCalledWith({
      skillId: "skill-1",
      limit: 1,
      cursor: null
    });
    expect(advancePersonalChat).not.toHaveBeenCalled();
    await expect
      .element(page.getByText(m.organization_skills_rollout_status_completed(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_personal_chat_failed()))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_personal_chat_not_applicable()))
      .not.toBeInTheDocument();
  });

  test("recovers the reviewed Personal Chat pin when the loader adoption read failed", async () => {
    const reviewedAdoption = {
      ...adoptionPage(),
      summary: {
        ...adoptionPage().summary,
        personal_chat: {
          revision_id: "revision-1",
          revision_number: 1,
          drift: "behind" as const
        }
      }
    };
    const getAdoption = vi.fn(async () => reviewedAdoption);
    const advancePersonalChat = vi.fn(async () => ({
      outcome: "advanced" as const,
      from_revision_number: 1,
      to_revision_number: 2
    }));
    const advanceAssistants = vi.fn(async () => ({
      run_id: "run-1",
      next_cursor: null,
      counts: {
        advanced: 0,
        concurrent_change: 0,
        incompatible: 0
      },
      outcomes: []
    }));

    render(OrganizationSkillDetailPage, {
      data: publicationLifecycleData({
        adoption: Promise.reject(new Error("Loader adoption unavailable")),
        advanceAssistants,
        advancePersonalChat,
        getAdoption
      }) as never
    });

    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    await page
      .getByRole("button", { name: m.organization_skills_publish_action(), exact: true })
      .last()
      .click();

    await vi.waitFor(() =>
      expect(advancePersonalChat).toHaveBeenCalledWith({
        skillId: "skill-1",
        expected_pinned_revision_id: "revision-1",
        expected_published_revision_id: "revision-2"
      })
    );
    expect(getAdoption).toHaveBeenCalledWith({
      skillId: "skill-1",
      limit: 1,
      cursor: null
    });
    await expect
      .element(page.getByText(m.organization_skills_rollout_personal_chat_advanced()))
      .toBeVisible();
  });

  test("shows a Personal Chat refusal without stopping the Assistant update", async () => {
    const advancePersonalChat = vi.fn(async () => {
      throw new Error("Refused");
    });
    const advanceAssistants = vi.fn(async () => ({
      run_id: "run-1",
      next_cursor: null,
      counts: {
        advanced: 1,
        concurrent_change: 0,
        incompatible: 0
      },
      outcomes: [{ assistant_id: "assistant-1", outcome: "advanced" as const }]
    }));
    const reviewedAdoption = {
      ...adoptionPage(),
      summary: {
        ...adoptionPage().summary,
        assistant_count: 1,
        personal_chat: {
          revision_id: "revision-1",
          revision_number: 1,
          drift: "behind" as const
        },
        revision_counts: [
          {
            revision_id: "revision-1",
            revision_number: 1,
            assistant_count: 1,
            app_count: 0,
            personal_chat_pinned: true
          }
        ]
      }
    };

    render(OrganizationSkillDetailPage, {
      data: publicationLifecycleData({
        adoption: Promise.resolve(reviewedAdoption),
        advanceAssistants,
        advancePersonalChat
      }) as never
    });

    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    await page
      .getByRole("button", { name: m.organization_skills_publish_action(), exact: true })
      .last()
      .click();

    await expect
      .element(page.getByText(m.organization_skills_rollout_status_completed(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_personal_chat_failed()))
      .toBeVisible();
    expect(advancePersonalChat).toHaveBeenCalledOnce();
    expect(advanceAssistants).toHaveBeenCalledOnce();
  });

  test("retains completed Assistant counts when a later chunk fails", async () => {
    const advanceAssistants = vi
      .fn()
      .mockResolvedValueOnce({
        run_id: "run-1",
        next_cursor: "cursor-2",
        counts: {
          advanced: 1,
          concurrent_change: 0,
          incompatible: 0
        },
        outcomes: [{ assistant_id: "assistant-1", outcome: "advanced" }]
      })
      .mockRejectedValueOnce(new Error("Chunk unavailable"));
    const reviewedAdoption = {
      ...adoptionPage(),
      summary: {
        ...adoptionPage().summary,
        assistant_count: 2,
        revision_counts: [
          {
            revision_id: "revision-1",
            revision_number: 1,
            assistant_count: 2,
            app_count: 0,
            personal_chat_pinned: false
          }
        ]
      }
    };

    render(OrganizationSkillDetailPage, {
      data: publicationLifecycleData({
        adoption: Promise.resolve(reviewedAdoption),
        advanceAssistants
      }) as never
    });

    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    await page
      .getByRole("button", { name: m.organization_skills_publish_action(), exact: true })
      .last()
      .click();

    await expect
      .element(page.getByText(m.organization_skills_rollout_status_failed(), { exact: true }))
      .toBeVisible();
    await expect
      .element(
        page.getByText(
          m.organization_skills_rollout_progress({
            updated: "1",
            total: "2"
          })
        )
      )
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.organization_skills_rollout_restart() }))
      .toBeVisible();
    await vi.waitFor(() => expect(invalidate).toHaveBeenCalledWith("organization:skills"));
  });

  test("stops between Assistant chunks and restarts a fresh server walk", async () => {
    const firstChunk = deferred<AssistantFleetAdvancePublic>();
    const restartChunk = deferred<AssistantFleetAdvancePublic>();
    const publish = vi.fn(async () => {});
    const advanceAssistants = vi
      .fn()
      .mockReturnValueOnce(firstChunk.promise)
      .mockReturnValueOnce(restartChunk.promise);
    const restartedResult: AssistantFleetAdvancePublic = {
      run_id: "run-2",
      next_cursor: null,
      counts: {
        advanced: 1,
        concurrent_change: 0,
        incompatible: 0
      },
      outcomes: [{ assistant_id: "assistant-2", outcome: "advanced" }]
    };
    const reviewedAdoption = {
      ...adoptionPage(),
      summary: {
        ...adoptionPage().summary,
        assistant_count: 2,
        revision_counts: [
          {
            revision_id: "revision-1",
            revision_number: 1,
            assistant_count: 2,
            app_count: 0,
            personal_chat_pinned: false
          }
        ]
      }
    };

    render(OrganizationSkillDetailPage, {
      data: publicationLifecycleData({
        adoption: Promise.resolve(reviewedAdoption),
        advanceAssistants,
        publish
      }) as never
    });

    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    await page
      .getByRole("button", { name: m.organization_skills_publish_action(), exact: true })
      .last()
      .click();
    const publishButton = page.getByRole("button", {
      name: m.organization_skills_publish_update_action()
    });
    const unpublishButton = page.getByRole("button", {
      name: m.organization_skills_unpublish_action(),
      exact: true
    });
    await expect.element(publishButton).toBeDisabled();
    await expect.element(unpublishButton).toBeDisabled();
    expect(publish).toHaveBeenCalledOnce();
    await page.getByRole("button", { name: m.organization_skills_rollout_stop() }).click();

    firstChunk.resolve({
      run_id: "run-1",
      next_cursor: "cursor-2",
      counts: {
        advanced: 1,
        concurrent_change: 0,
        incompatible: 0
      },
      outcomes: [{ assistant_id: "assistant-1", outcome: "advanced" }]
    });

    await expect
      .element(page.getByText(m.organization_skills_rollout_status_stopped(), { exact: true }))
      .toBeVisible();
    await expect.element(publishButton).toBeEnabled();
    await expect.element(unpublishButton).toBeEnabled();
    expect(advanceAssistants).toHaveBeenCalledTimes(1);

    await page.getByRole("button", { name: m.organization_skills_rollout_restart() }).click();
    await expect.element(publishButton).toBeDisabled();
    await expect.element(unpublishButton).toBeDisabled();
    await vi.waitFor(() => expect(advanceAssistants).toHaveBeenCalledTimes(2));
    expect(advanceAssistants).toHaveBeenLastCalledWith({
      skillId: "skill-1",
      expected_published_revision_id: "revision-2",
      cursor: null
    });
    restartChunk.resolve(restartedResult);
    await expect
      .element(page.getByText(m.organization_skills_rollout_status_completed(), { exact: true }))
      .toBeVisible();
    await expect
      .element(
        page.getByText(
          m.organization_skills_rollout_progress({
            updated: "1",
            total: "1"
          })
        )
      )
      .toBeVisible();
  });

  test("discards a running receipt and ignores its late response after navigation", async () => {
    const lateChunk = deferred<AssistantFleetAdvancePublic>();
    const advanceAssistants = vi.fn(() => lateChunk.promise);
    const firstData = publicationLifecycleData({ advanceAssistants });
    const rendered = render(OrganizationSkillDetailPage, { data: firstData as never });

    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    await page
      .getByRole("button", { name: m.organization_skills_publish_action(), exact: true })
      .last()
      .click();
    await vi.waitFor(() => expect(advanceAssistants).toHaveBeenCalledOnce());
    await expect
      .element(page.getByText(m.organization_skills_rollout_status_running(), { exact: true }))
      .toBeVisible();

    await rendered.rerender({
      data: publicationLifecycleData({
        skill: { ...updatePendingSkill(), id: "skill-2" },
        advanceAssistants
      }) as never
    });
    await expect
      .element(page.getByText(m.organization_skills_rollout_title()))
      .not.toBeInTheDocument();

    lateChunk.resolve({
      run_id: "run-1",
      next_cursor: null,
      counts: {
        advanced: 1,
        concurrent_change: 0,
        incompatible: 0
      },
      outcomes: [{ assistant_id: "assistant-1", outcome: "advanced" }]
    });

    await expect
      .element(page.getByText(m.organization_skills_rollout_title()))
      .not.toBeInTheDocument();
    expect(invalidate).not.toHaveBeenCalled();
  });

  test("discards an old rollout when the current Skill revision changes", async () => {
    const lateChunk = deferred<AssistantFleetAdvancePublic>();
    const advanceAssistants = vi.fn(() => lateChunk.promise);
    const firstData = publicationLifecycleData({ advanceAssistants });
    const rendered = render(OrganizationSkillDetailPage, { data: firstData as never });

    await page.getByRole("button", { name: m.organization_skills_publish_update_action() }).click();
    await page
      .getByRole("button", { name: m.organization_skills_publish_action(), exact: true })
      .last()
      .click();
    await vi.waitFor(() => expect(advanceAssistants).toHaveBeenCalledOnce());

    const nextRevision = revision(3);
    await rendered.rerender({
      data: publicationLifecycleData({
        skill: {
          ...updatePendingSkill(),
          current_revision_id: nextRevision.id,
          current_revision_number: nextRevision.revision_number,
          display_name: nextRevision.display_name,
          description: nextRevision.description,
          content_digest: nextRevision.content_digest,
          current_revision: nextRevision
        },
        advanceAssistants
      }) as never
    });
    await expect
      .element(page.getByText(m.organization_skills_rollout_title()))
      .not.toBeInTheDocument();

    lateChunk.resolve({
      run_id: "run-1",
      next_cursor: null,
      counts: {
        advanced: 1,
        concurrent_change: 0,
        incompatible: 0
      },
      outcomes: [{ assistant_id: "assistant-1", outcome: "advanced" }]
    });

    await expect
      .element(page.getByText(m.organization_skills_rollout_title()))
      .not.toBeInTheDocument();
    expect(invalidate).not.toHaveBeenCalled();
  });

  test("keeps a publication change committed when refreshing the page data fails", async () => {
    const unpublish = vi.fn(async () => {});
    invalidate.mockRejectedValueOnce(new Error("Refresh failed"));

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish
            }
          }
        }
      } as never
    });

    await page
      .getByRole("button", { name: m.organization_skills_unpublish_action(), exact: true })
      .click();
    await page
      .getByRole("button", { name: m.organization_skills_unpublish_action(), exact: true })
      .last()
      .click();

    await vi.waitFor(() => expect(unpublish).toHaveBeenCalledTimes(1));
    await expect
      .element(page.getByText(m.organization_skills_refresh_after_mutation_warning()))
      .toBeVisible();
    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_unpublish_title() }))
      .not.toBeInTheDocument();
  });

  test("requires a reason and keeps saved bindings while blocking execution", async () => {
    const blockedState: SkillExecutionBlockState = {
      skill_id: "skill-1",
      block: {
        id: "block-1",
        skill_id: "skill-1",
        blocked_by_user_id: "admin-1",
        reason: "Confirmed unsafe instructions",
        blocked_at: "2026-07-23T17:30:00Z"
      }
    };
    const blockSkillExecution = vi.fn().mockResolvedValue(blockedState);

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: unblockedState(),
        eneo: {
          settings: {
            blockSkillExecution,
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution: vi.fn()
          },
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page
      .getByRole("button", { name: m.organization_skills_execution_block_action() })
      .click();
    const confirm = page
      .getByRole("button", { name: m.organization_skills_execution_block_confirm() })
      .last();
    await expect.element(confirm).toBeDisabled();

    await page
      .getByLabelText(m.organization_skills_execution_reason_label())
      .fill("  Confirmed unsafe instructions  ");
    await expect.element(confirm).toBeEnabled();
    await confirm.click();

    await vi.waitFor(() =>
      expect(blockSkillExecution).toHaveBeenCalledWith({
        skillId: "skill-1",
        reason: "Confirmed unsafe instructions"
      })
    );
    await expect
      .element(
        page
          .getByRole("alert")
          .getByText(m.organization_skills_execution_blocked_status(), { exact: true })
      )
      .toBeVisible();
    await expect.element(page.getByText("Confirmed unsafe instructions")).toBeVisible();
    await expect
      .element(
        page.getByRole("heading", {
          name: m.organization_skills_adoption_heading()
        })
      )
      .toBeVisible();
  });

  test("releases only the block reviewed by the administrator", async () => {
    const initialBlock: SkillExecutionBlockState = {
      skill_id: "skill-1",
      block: {
        id: "block-1",
        skill_id: "skill-1",
        blocked_by_user_id: "admin-1",
        reason: "Confirmed unsafe instructions",
        blocked_at: "2026-07-23T17:30:00Z"
      }
    };
    const unblockSkillExecution = vi.fn().mockResolvedValue(unblockedState());

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: initialBlock,
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock: vi.fn(),
            unblockSkillExecution
          },
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page
      .getByRole("button", { name: m.organization_skills_execution_unblock_action() })
      .click();
    await page
      .getByLabelText(m.organization_skills_execution_reason_label())
      .fill("Removed the harmful revision");
    await page
      .getByRole("button", { name: m.organization_skills_execution_unblock_confirm() })
      .last()
      .click();

    await vi.waitFor(() =>
      expect(unblockSkillExecution).toHaveBeenCalledWith({
        skillId: "skill-1",
        expectedBlockId: "block-1",
        reason: "Removed the harmful revision"
      })
    );
    await expect
      .element(page.getByText(m.organization_skills_execution_available_status()))
      .toBeVisible();
  });

  test("does not claim the block state is current when the reread fails", async () => {
    const initialBlock: SkillExecutionBlockState = {
      skill_id: "skill-1",
      block: {
        id: "block-1",
        skill_id: "skill-1",
        blocked_by_user_id: "admin-1",
        reason: "Initial incident",
        blocked_at: "2026-07-23T17:30:00Z"
      }
    };
    const unblockSkillExecution = vi
      .fn()
      .mockRejectedValue(
        new EneoError(
          "Concurrent change",
          "RESPONSE",
          409,
          SKILL_EXECUTION_BLOCK_CONFLICT,
          {},
          { endpoint: "POST@execution-block/unblock" }
        )
      );
    const getSkillExecutionBlock = vi.fn().mockRejectedValue(new Error("Unavailable"));

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: { items: [], count: 0, limit: 25, next_cursor: null },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: initialBlock,
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock,
            unblockSkillExecution
          },
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page
      .getByRole("button", { name: m.organization_skills_execution_unblock_action() })
      .click();
    const reason = page.getByLabelText(m.organization_skills_execution_reason_label());
    await reason.fill("Reviewed and remediated");
    await page
      .getByRole("button", { name: m.organization_skills_execution_unblock_confirm() })
      .last()
      .click();

    // The conflict copy points at the state shown below. When that state could
    // not be refreshed, saying so is the only honest option.
    await expect
      .element(page.getByText(m.organization_skills_execution_refresh_error()))
      .toBeVisible();
    await expect.element(page.getByText(m.eneo_error_9052())).not.toBeInTheDocument();
    await expect.element(reason).toHaveValue("Reviewed and remediated");
  });

  test("reloads a concurrent block change without losing the entered reason", async () => {
    const initialBlock: SkillExecutionBlockState = {
      skill_id: "skill-1",
      block: {
        id: "block-1",
        skill_id: "skill-1",
        blocked_by_user_id: "admin-1",
        reason: "Initial incident",
        blocked_at: "2026-07-23T17:30:00Z"
      }
    };
    const replacementBlock: SkillExecutionBlockState = {
      skill_id: "skill-1",
      block: {
        id: "block-2",
        skill_id: "skill-1",
        blocked_by_user_id: "admin-2",
        reason: "Expanded incident review",
        blocked_at: "2026-07-23T17:45:00Z"
      }
    };
    const unblockSkillExecution = vi.fn().mockRejectedValue(
      new EneoError(
        "Concurrent change",
        "RESPONSE",
        409,
        // The execution block has its own reason code; it no longer borrows
        // the revision conflict, which carries a different recovery.
        SKILL_EXECUTION_BLOCK_CONFLICT,
        {},
        { endpoint: "POST@execution-block/unblock" }
      )
    );
    const getSkillExecutionBlock = vi.fn().mockResolvedValue(replacementBlock);

    render(OrganizationSkillDetailPage, {
      data: {
        skill: updatePendingSkill(),
        published: publishedSkill(),
        revisionPage: {
          items: [],
          count: 0,
          limit: 25,
          next_cursor: null
        },
        adoptionPage: Promise.resolve(adoptionPage()),
        executionBlock: initialBlock,
        eneo: {
          settings: {
            blockSkillExecution: vi.fn(),
            getSkillExecutionBlock,
            unblockSkillExecution
          },
          skills: {
            organization: {
              createRevision: vi.fn(),
              getAdoption: vi.fn(),
              getRevision: vi.fn(),
              listRevisionSummaries: vi.fn(),
              publish: vi.fn(),
              restoreRevision: vi.fn(),
              unpublish: vi.fn()
            }
          }
        }
      } as never
    });

    await page
      .getByRole("button", { name: m.organization_skills_execution_unblock_action() })
      .click();
    const reason = page.getByLabelText(m.organization_skills_execution_reason_label());
    await reason.fill("Reviewed and remediated");
    await page
      .getByRole("button", { name: m.organization_skills_execution_unblock_confirm() })
      .last()
      .click();

    await expect.element(page.getByText(m.eneo_error_9052())).toBeVisible();
    await expect
      .element(page.getByRole("alertdialog").getByText("Expanded incident review"))
      .toBeVisible();
    await expect.element(reason).toHaveValue("Reviewed and remediated");
    expect(getSkillExecutionBlock).toHaveBeenCalledWith({ skillId: "skill-1" });
  });

  test("lets a refreshed loader state replace the committed response override", async () => {
    const committedBlock: SkillExecutionBlockState = {
      skill_id: "skill-1",
      block: {
        id: "block-1",
        skill_id: "skill-1",
        blocked_by_user_id: "admin-1",
        reason: "Initial incident",
        blocked_at: "2026-07-23T17:30:00Z"
      }
    };
    const refreshedBlock: SkillExecutionBlockState = {
      skill_id: "skill-1",
      block: {
        id: "block-2",
        skill_id: "skill-1",
        blocked_by_user_id: "admin-2",
        reason: "Expanded incident review",
        blocked_at: "2026-07-23T17:45:00Z"
      }
    };
    const data = {
      skill: updatePendingSkill(),
      published: publishedSkill(),
      revisionPage: {
        items: [],
        count: 0,
        limit: 25,
        next_cursor: null
      },
      adoptionPage: Promise.resolve(adoptionPage()),
      executionBlock: unblockedState(),
      eneo: {
        settings: {
          blockSkillExecution: vi.fn().mockResolvedValue(committedBlock),
          getSkillExecutionBlock: vi.fn(),
          unblockSkillExecution: vi.fn()
        },
        skills: {
          organization: {
            createRevision: vi.fn(),
            getAdoption: vi.fn(),
            getRevision: vi.fn(),
            listRevisionSummaries: vi.fn(),
            publish: vi.fn(),
            restoreRevision: vi.fn(),
            unpublish: vi.fn()
          }
        }
      }
    };
    const rendered = render(OrganizationSkillDetailPage, { data: data as never });

    await page
      .getByRole("button", { name: m.organization_skills_execution_block_action() })
      .click();
    await page
      .getByLabelText(m.organization_skills_execution_reason_label())
      .fill("Initial incident");
    await page
      .getByRole("button", { name: m.organization_skills_execution_block_confirm() })
      .last()
      .click();
    await expect.element(page.getByText("Initial incident")).toBeVisible();

    await rendered.rerender({
      data: {
        ...data,
        executionBlock: refreshedBlock
      } as never
    });

    await expect.element(page.getByText("Expanded incident review")).toBeVisible();
    await expect.element(page.getByText("Initial incident")).not.toBeInTheDocument();
  });
});
