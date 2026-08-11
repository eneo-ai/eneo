import type { SkillAdoptionProjectionPagePublic } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import SkillAdoptionProjection from "./SkillAdoptionProjection.svelte";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function adoptionPage({
  items = [
    {
      kind: "assistant" as const,
      resource_id: "assistant-1",
      name: "HR Assistant",
      space_id: "space-1",
      space_name: "People and culture",
      revision_id: "revision-1",
      revision_number: 1,
      drift: "behind" as const
    }
  ],
  nextCursor = null,
  includeSummary = true
}: {
  items?: SkillAdoptionProjectionPagePublic["items"];
  nextCursor?: string | null;
  includeSummary?: boolean;
} = {}): SkillAdoptionProjectionPagePublic {
  const assistantCount = items.filter((item) => item.kind === "assistant").length;
  const appCount = items.filter((item) => item.kind === "app").length + (nextCursor ? 1 : 0);

  return {
    summary: includeSummary
      ? {
          assistant_count: assistantCount,
          app_count: appCount,
          distinct_space_count: new Set(items.map((item) => item.space_id)).size,
          behind_published_count: items.filter((item) => item.drift === "behind").length + 1,
          personal_chat: {
            revision_id: "revision-1",
            revision_number: 1,
            drift: "behind"
          },
          revision_counts: [
            {
              revision_id: "revision-1",
              revision_number: 1,
              assistant_count: items.filter((item) => item.kind === "assistant").length,
              app_count: items.filter((item) => item.kind === "app").length,
              personal_chat_pinned: true
            }
          ]
        }
      : null,
    items,
    limit: 25,
    next_cursor: nextCursor
  };
}

function emptyAdoptionPage(): SkillAdoptionProjectionPagePublic {
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

describe("Skill adoption projection", () => {
  test("announces rollout progress and exposes only the action for the current state", async () => {
    const onStop = vi.fn();
    const onRestart = vi.fn();
    const rendered = render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage(),
      getOrganizationSkillAdoption: vi.fn(),
      run: {
        status: "running",
        assistantsIncluded: true,
        provisionalTotal: 5,
        advanced: 3,
        concurrentChange: 1,
        activationUnavailable: 1,
        contextWindow: 1,
        personalChat: "failed",
        apps: null
      },
      onStop,
      onRestart
    });

    await expect
      .element(
        page.getByText(
          m.organization_skills_rollout_progress({
            updated: "3",
            total: "6"
          })
        )
      )
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_status_running(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_updated()).last())
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_concurrent_change()).last())
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_activation_unavailable()).last())
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_context_window()).last())
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_personal_chat_failed()))
      .toBeVisible();
    await page.getByRole("button", { name: m.organization_skills_rollout_stop() }).click();
    expect(onStop).toHaveBeenCalledOnce();
    await expect
      .element(page.getByRole("button", { name: m.organization_skills_rollout_restart() }))
      .not.toBeInTheDocument();

    await rendered.rerender({
      skillId: "skill-1",
      initialPage: adoptionPage(),
      getOrganizationSkillAdoption: vi.fn(),
      run: {
        status: "stopped",
        assistantsIncluded: true,
        provisionalTotal: 5,
        advanced: 3,
        concurrentChange: 1,
        activationUnavailable: 1,
        contextWindow: 1,
        personalChat: "failed",
        apps: null
      },
      onStop,
      onRestart
    });

    await expect
      .element(page.getByText(m.organization_skills_rollout_status_stopped(), { exact: true }))
      .toBeVisible();
    await page.getByRole("button", { name: m.organization_skills_rollout_restart() }).click();
    expect(onRestart).toHaveBeenCalledOnce();
    await expect
      .element(page.getByRole("button", { name: m.organization_skills_rollout_stop() }))
      .not.toBeInTheDocument();

    await rendered.rerender({
      skillId: "skill-1",
      initialPage: adoptionPage(),
      getOrganizationSkillAdoption: vi.fn(),
      run: {
        status: "completed",
        assistantsIncluded: true,
        provisionalTotal: 5,
        advanced: 3,
        concurrentChange: 1,
        activationUnavailable: 1,
        contextWindow: 1,
        personalChat: "not_applicable",
        apps: null
      },
      onStop,
      onRestart
    });

    await expect
      .element(page.getByText(m.organization_skills_rollout_status_completed(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_personal_chat_not_applicable()))
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.organization_skills_rollout_restart() }))
      .not.toBeInTheDocument();
    await expect
      .element(page.getByRole("button", { name: m.organization_skills_rollout_stop() }))
      .not.toBeInTheDocument();

    await rendered.rerender({
      skillId: "skill-1",
      initialPage: adoptionPage(),
      getOrganizationSkillAdoption: vi.fn(),
      run: {
        status: "failed",
        assistantsIncluded: true,
        provisionalTotal: 5,
        advanced: 3,
        concurrentChange: 1,
        activationUnavailable: 1,
        contextWindow: 1,
        personalChat: "advanced",
        apps: null
      },
      onStop,
      onRestart
    });

    await expect
      .element(page.getByText(m.organization_skills_rollout_status_failed(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.organization_skills_rollout_restart() }))
      .toBeVisible();
  });

  test("shows App rollout results", async () => {
    const appProjection = adoptionPage({
      items: [
        {
          kind: "app",
          resource_id: "app-1",
          name: "Payroll workflow",
          space_id: "space-1",
          space_name: "People and culture",
          revision_id: "revision-1",
          revision_number: 1,
          drift: "behind"
        }
      ]
    });
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: appProjection,
      getOrganizationSkillAdoption: vi.fn(),
      publishedRevisionId: "revision-2",
      run: {
        status: "completed",
        assistantsIncluded: false,
        provisionalTotal: 0,
        advanced: 0,
        concurrentChange: 0,
        activationUnavailable: 0,
        contextWindow: 0,
        personalChat: "not_applicable",
        apps: {
          status: "completed",
          provisionalTotal: 2,
          advanced: 1,
          concurrentChange: 0,
          contextWindow: 1
        }
      }
    });

    await expect
      .element(page.getByText(m.organization_skills_rollout_apps_title(), { exact: true }))
      .toBeVisible();
    await expect
      .element(
        page.getByText(m.organization_skills_rollout_apps_progress({ updated: "1", total: "2" }))
      )
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_apps_queued_runs_unchanged()))
      .toBeVisible();
  });

  test("offers one App-only recovery action when no Personal Chat or Assistant is behind", async () => {
    const appProjection = adoptionPage({
      items: [
        {
          kind: "app",
          resource_id: "app-1",
          name: "Payroll workflow",
          space_id: "space-1",
          space_name: "People and culture",
          revision_id: "revision-1",
          revision_number: 1,
          drift: "behind"
        }
      ]
    });
    const onStartOutdatedBindingsUpdate = vi.fn();
    if (appProjection.summary?.personal_chat) {
      appProjection.summary.personal_chat.drift = "current";
      appProjection.summary.personal_chat.revision_id = "revision-2";
      appProjection.summary.personal_chat.revision_number = 2;
    }

    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: appProjection,
      getOrganizationSkillAdoption: vi.fn(),
      publishedRevisionId: "revision-2",
      onStartOutdatedBindingsUpdate,
      run: null
    });
    await page
      .getByRole("button", { name: m.organization_skills_rollout_recovery_action() })
      .click();
    expect(onStartOutdatedBindingsUpdate).toHaveBeenCalledOnce();
    expect(onStartOutdatedBindingsUpdate).toHaveBeenCalledWith(appProjection, {
      assistants: false,
      apps: true
    });
  });

  test("offers one Assistant and Personal Chat recovery action without Apps", async () => {
    const assistantProjection = adoptionPage();
    const onStartOutdatedBindingsUpdate = vi.fn();

    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: assistantProjection,
      getOrganizationSkillAdoption: vi.fn(),
      publishedRevisionId: "revision-2",
      onStartOutdatedBindingsUpdate,
      run: null
    });

    await page
      .getByRole("button", { name: m.organization_skills_rollout_recovery_action() })
      .click();
    expect(onStartOutdatedBindingsUpdate).toHaveBeenCalledWith(assistantProjection, {
      assistants: true,
      apps: false
    });
  });

  test("shows server-owned summary, Personal Chat pin, revision counts, and resource drift", async () => {
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage(),
      getOrganizationSkillAdoption: vi.fn()
    });

    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_adoption_heading() }))
      .toBeVisible();
    await expect.element(page.getByText("HR Assistant")).toBeVisible();
    await expect.element(page.getByText("People and culture").last()).toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_adoption_drift_behind()).last())
      .toBeVisible();
    await expect
      .element(
        page.getByText(
          m.organization_skills_adoption_personal_chat_pinned({
            version: "1"
          })
        )
      )
      .toBeVisible();
    await expect
      .element(
        page.getByRole("heading", {
          name: m.organization_skills_adoption_revision_breakdown_heading()
        })
      )
      .toBeVisible();
    await expect.element(page.getByRole("table").first()).toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_rollout_title()))
      .not.toBeInTheDocument();
  });

  test("offers the Personal Chat update only through the reviewed pin", async () => {
    const onAdvancePersonalChat = vi.fn();
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage(),
      getOrganizationSkillAdoption: vi.fn(),
      onAdvancePersonalChat
    });

    await page
      .getByRole("button", {
        name: m.organization_skills_adoption_personal_chat_advance_action()
      })
      .click();

    expect(onAdvancePersonalChat).toHaveBeenCalledWith({
      revisionId: "revision-1",
      revisionNumber: 1
    });
  });

  test("shows no Personal Chat update without a handler or when the pin is current", async () => {
    const rendered = render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage(),
      getOrganizationSkillAdoption: vi.fn()
    });

    await expect
      .element(
        page.getByText(m.organization_skills_adoption_personal_chat_pinned({ version: "1" }))
      )
      .toBeVisible();
    await expect
      .element(
        page.getByRole("button", {
          name: m.organization_skills_adoption_personal_chat_advance_action()
        })
      )
      .not.toBeInTheDocument();

    const current = adoptionPage();
    if (current.summary?.personal_chat) {
      current.summary.personal_chat.drift = "current";
    }
    await rendered.rerender({
      skillId: "skill-1",
      initialPage: current,
      getOrganizationSkillAdoption: vi.fn(),
      onAdvancePersonalChat: vi.fn()
    });
    await expect
      .element(
        page.getByRole("button", {
          name: m.organization_skills_adoption_personal_chat_advance_action()
        })
      )
      .not.toBeInTheDocument();
  });

  test("distinguishes an empty structural projection from runtime usage", async () => {
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: emptyAdoptionPage(),
      getOrganizationSkillAdoption: vi.fn()
    });

    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_adoption_empty_title() }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_adoption_empty_description()))
      .toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_adoption_description()))
      .toBeVisible();
  });

  test("labels an unpublished source without relying on colour", async () => {
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage({
        items: [
          {
            kind: "app",
            resource_id: "app-1",
            name: "Policy App",
            space_id: "space-1",
            space_name: "Operations",
            revision_id: "revision-1",
            revision_number: 1,
            drift: "unpublished"
          }
        ]
      }),
      getOrganizationSkillAdoption: vi.fn()
    });

    await expect
      .element(page.getByText(m.organization_skills_adoption_drift_unpublished()).last())
      .toBeVisible();
  });

  test("announces the initial loading state", async () => {
    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: null,
      initialLoading: true,
      getOrganizationSkillAdoption: vi.fn()
    });

    await expect
      .element(
        page.getByRole("status", {
          name: m.organization_skills_adoption_loading()
        })
      )
      .toBeVisible();
  });

  test("keeps an initial failure local to adoption and allows retry", async () => {
    const getOrganizationSkillAdoption = vi.fn().mockResolvedValue(emptyAdoptionPage());

    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: null,
      initialError: true,
      getOrganizationSkillAdoption
    });

    await expect
      .element(page.getByText(m.organization_skills_adoption_error_title()))
      .toBeVisible();
    await page.getByRole("button", { name: m.retry() }).click();

    await vi.waitFor(() =>
      expect(getOrganizationSkillAdoption).toHaveBeenCalledWith("skill-1", {
        limit: 25,
        cursor: null
      })
    );
    await expect
      .element(page.getByRole("heading", { name: m.organization_skills_adoption_empty_title() }))
      .toBeVisible();
  });

  test("retains a failed page cursor and appends resources after retry", async () => {
    const secondPage = adoptionPage({
      items: [
        {
          kind: "app",
          resource_id: "app-1",
          name: "Onboarding App",
          space_id: "space-2",
          space_name: "Employee services",
          revision_id: "revision-2",
          revision_number: 2,
          drift: "current"
        }
      ],
      includeSummary: false
    });
    const getOrganizationSkillAdoption = vi
      .fn()
      .mockRejectedValueOnce(new Error("Unavailable"))
      .mockResolvedValueOnce(secondPage);

    render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage({ nextCursor: "next-page" }),
      getOrganizationSkillAdoption
    });

    await page.getByRole("button", { name: m.organization_skills_adoption_load_more() }).click();
    await expect.element(page.getByRole("alert")).toBeVisible();
    await page.getByRole("button", { name: m.retry() }).click();

    await vi.waitFor(() => expect(getOrganizationSkillAdoption).toHaveBeenCalledTimes(2));
    expect(getOrganizationSkillAdoption).toHaveBeenLastCalledWith("skill-1", {
      limit: 25,
      cursor: "next-page"
    });
    await expect.element(page.getByText("HR Assistant")).toBeVisible();
    await expect.element(page.getByText("Onboarding App")).toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_adoption_drift_current()).last())
      .toBeVisible();
    await expect
      .element(
        page.getByText(
          m.organization_skills_adoption_resources_shown({
            shown: "2",
            total: "2"
          })
        )
      )
      .toBeInTheDocument();
  });

  test("ignores a continuation response from before the projection refresh", async () => {
    const staleContinuation = deferred<SkillAdoptionProjectionPagePublic>();
    const getOrganizationSkillAdoption = vi
      .fn()
      .mockReturnValueOnce(staleContinuation.promise)
      .mockResolvedValueOnce(adoptionPage({ items: [], includeSummary: false }));
    const refreshedPage = adoptionPage({
      items: [
        {
          kind: "assistant",
          resource_id: "assistant-refreshed",
          name: "Refreshed Assistant",
          space_id: "space-refreshed",
          space_name: "Refreshed Space",
          revision_id: "revision-2",
          revision_number: 2,
          drift: "current"
        }
      ],
      nextCursor: "refreshed-next"
    });
    const rendered = render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: adoptionPage({ nextCursor: "stale-next" }),
      getOrganizationSkillAdoption
    });

    await page.getByRole("button", { name: m.organization_skills_adoption_load_more() }).click();
    await vi.waitFor(() =>
      expect(getOrganizationSkillAdoption).toHaveBeenCalledWith("skill-1", {
        limit: 25,
        cursor: "stale-next"
      })
    );

    await rendered.rerender({
      skillId: "skill-1",
      initialPage: refreshedPage,
      getOrganizationSkillAdoption
    });
    await expect.element(page.getByText("Refreshed Assistant")).toBeVisible();

    staleContinuation.resolve(
      adoptionPage({
        items: [
          {
            kind: "app",
            resource_id: "app-stale",
            name: "Stale App",
            space_id: "space-stale",
            space_name: "Stale Space",
            revision_id: "revision-1",
            revision_number: 1,
            drift: "behind"
          }
        ],
        nextCursor: "stale-tail",
        includeSummary: false
      })
    );

    await expect.element(page.getByText("Stale App")).not.toBeInTheDocument();
    await expect.element(page.getByText("HR Assistant")).not.toBeInTheDocument();
    await expect
      .element(page.getByText(m.organization_skills_adoption_drift_current()).last())
      .toBeVisible();

    await page.getByRole("button", { name: m.organization_skills_adoption_load_more() }).click();
    await vi.waitFor(() =>
      expect(getOrganizationSkillAdoption).toHaveBeenLastCalledWith("skill-1", {
        limit: 25,
        cursor: "refreshed-next"
      })
    );
  });

  test("ignores an initial retry failure after navigating to another Skill", async () => {
    const staleRetry = deferred<SkillAdoptionProjectionPagePublic>();
    const getOrganizationSkillAdoption = vi.fn().mockReturnValueOnce(staleRetry.promise);
    const currentPage = adoptionPage({
      items: [
        {
          kind: "app",
          resource_id: "app-current",
          name: "Current App",
          space_id: "space-current",
          space_name: "Current Space",
          revision_id: "revision-3",
          revision_number: 3,
          drift: "current"
        }
      ]
    });
    const rendered = render(SkillAdoptionProjection, {
      skillId: "skill-1",
      initialPage: null,
      initialError: true,
      getOrganizationSkillAdoption
    });

    await page.getByRole("button", { name: m.retry() }).click();
    await vi.waitFor(() =>
      expect(getOrganizationSkillAdoption).toHaveBeenCalledWith("skill-1", {
        limit: 25,
        cursor: null
      })
    );

    await rendered.rerender({
      skillId: "skill-2",
      initialPage: currentPage,
      getOrganizationSkillAdoption
    });
    await expect.element(page.getByText("Current App")).toBeVisible();

    staleRetry.reject(new Error("Stale retry failed"));

    await expect.element(page.getByText("Current App")).toBeVisible();
    await expect
      .element(page.getByText(m.organization_skills_adoption_error()))
      .not.toBeInTheDocument();
  });
});
