import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import type { Schema } from "../src/lib/api/models";
import { expect, test } from "./csp";
import { apiPostJson, sessionResponseHeaders, uniqueName } from "./helpers";

const content = (name: string) => ({
  display_name: name,
  description: `Description for ${name}`,
  instructions: `Instructions for ${name}`
});

async function createSkill(page: Page) {
  await page.goto("/spaces/organization/skills");
  return apiPostJson<Schema<"OrganizationSkillPublic">>(page, "/skills/organization/", {
    slug: `skills-parity-${Date.now()}`,
    ...content(uniqueName("Skill source"))
  });
}

test(
  "keeps the selected source open after a real restore conflict and compares the latest current version",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const skill = await createSkill(page);
    const path = `/skills/organization/${skill.id}`;
    await apiPostJson<Schema<"SkillRevisionPublic">>(
      page,
      `${path}/revisions/`,
      content("Reviewed version")
    );
    await page.goto(`/spaces/organization/skills/${skill.id}`);
    await page.getByRole("button", { name: "Visa version 1", exact: true }).click();
    const preview = page.getByRole("dialog", { name: "Version 1", exact: true });
    await expect(
      preview.getByText(skill.current_revision.instructions, { exact: true })
    ).toBeVisible();
    await apiPostJson<Schema<"SkillRevisionPublic">>(
      page,
      `${path}/revisions/`,
      content("Concurrent version")
    );
    await preview.getByRole("button", { name: "Återställ som en ny version", exact: true }).click();
    const confirmation = page.getByRole("alertdialog");
    const restores: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/restore/"))
        restores.push(request.postData() ?? "");
    });
    const conflict = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.endsWith("/restore/") && response.status() === 409
    );
    await confirmation
      .getByRole("button", { name: "Återställ som en ny version", exact: true })
      .click();
    await conflict;
    await expect(preview).toBeVisible();
    await expect(
      preview.getByText("Versionen kunde inte återställas.", { exact: true })
    ).toBeVisible();
    await expect(preview.getByRole("heading", { name: "Version 3", exact: false })).toBeVisible();
    await expect(
      preview.getByText("Instructions for Concurrent version", { exact: true })
    ).toBeVisible();
    expect(restores).toHaveLength(1);
    await expect(preview).toHaveCSS("opacity", "1");
    const source = preview
      .locator("section")
      .filter({ has: page.getByText(skill.current_revision.instructions, { exact: true }) });
    const current = preview
      .locator("section")
      .filter({ has: page.getByText("Instructions for Concurrent version", { exact: true }) });
    const sourceBox = await source.boundingBox();
    const currentBox = await current.boundingBox();
    expect(sourceBox).not.toBeNull();
    expect(currentBox).not.toBeNull();
    expect(currentBox!.x).toBeGreaterThan(sourceBox!.x + sourceBox!.width);
    await page.screenshot({
      path: testInfo.outputPath("restore-conflict-desktop.png"),
      fullPage: true
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(
      preview.getByText("Instructions for Concurrent version", { exact: true })
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390
    );
    type AxePage = ConstructorParameters<typeof AxeBuilder>[0]["page"];
    const { violations } = await new AxeBuilder({ page: page as unknown as AxePage })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(violations).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath("restore-conflict-phone.png"),
      fullPage: true
    });
    expect(errors).toEqual([]);
  }
);

test(
  "shows separate rollout reasons and resumes an app failure without replaying completed assistants",
  { tag: "@vite" },
  async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const skill = await createSkill(page);
    const path = `/skills/organization/${skill.id}`;
    await apiPostJson(page, `${path}/publish/`, {
      expected_revision_id: skill.current_revision_id
    });
    const next = await apiPostJson<Schema<"SkillRevisionPublic">>(
      page,
      `${path}/revisions/`,
      content("Published target")
    );
    await apiPostJson(page, `${path}/publish/`, { expected_revision_id: next.id });
    const assistantId = "00000000-0000-4000-8000-000000000001";
    const appId = "00000000-0000-4000-8000-000000000002";
    const adoption: Schema<"SkillAdoptionProjectionPagePublic"> = {
      summary: {
        assistant_count: 3,
        app_count: 1,
        distinct_space_count: 1,
        behind_published_count: 4,
        personal_chat: {
          revision_id: skill.current_revision_id,
          revision_number: 1,
          drift: "behind"
        },
        revision_counts: [
          {
            revision_id: skill.current_revision_id,
            revision_number: 1,
            assistant_count: 3,
            app_count: 1,
            personal_chat_pinned: true
          }
        ]
      },
      items: [
        {
          kind: "assistant",
          resource_id: assistantId,
          name: "Fixture assistant",
          space_id: assistantId,
          space_name: "Fixture personal space",
          revision_id: skill.current_revision_id,
          revision_number: 1,
          drift: "behind",
          owner_name: "Fixture owner",
          can_open: false
        }
      ],
      limit: 100,
      next_cursor: null,
      matched_count: 1
    };
    // Typed fixtures isolate pagination, failure and stop timing. The Skill and
    // its published revisions above use the real cookie-authenticated API.
    await page.route(`**/api/v1${path}/adoption/**`, (route) =>
      route.fulfill({
        json: adoption,
        headers: sessionResponseHeaders(route)
      })
    );
    await page.route(`**/api/v1${path}/personal-chat/advance/`, (route) =>
      route.fulfill({
        json: {
          outcome: "advanced",
          from_revision_number: 1,
          to_revision_number: 2
        } satisfies Schema<"PersonalChatPinAdvancePublic">,
        headers: sessionResponseHeaders(route)
      })
    );
    let releaseFirst!: () => void;
    const firstPage = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    let assistantCalls = 0;
    await page.route(`**/api/v1${path}/assistants/advance/`, async (route) => {
      assistantCalls += 1;
      const cursor = (route.request().postDataJSON() as { cursor: string | null }).cursor;
      if (!cursor) await firstPage;
      const result: Schema<"AssistantFleetAdvancePublic"> = {
        run_id: assistantId,
        next_cursor: cursor ? null : "next",
        counts: cursor
          ? { advanced: 1, concurrent_change: 0, incompatible: 0 }
          : { advanced: 0, concurrent_change: 0, incompatible: 2 },
        outcomes: cursor
          ? [{ assistant_id: assistantId, outcome: "advanced", reason: null }]
          : [
              {
                assistant_id: assistantId,
                outcome: "incompatible",
                reason: "activation_unavailable"
              },
              {
                assistant_id: "00000000-0000-4000-8000-000000000003",
                outcome: "incompatible",
                reason: "context_window"
              }
            ]
      };
      await route.fulfill({ json: result, headers: sessionResponseHeaders(route) });
    });
    let appCalls = 0;
    await page.route(`**/api/v1${path}/apps/advance/`, (route) => {
      appCalls += 1;
      return route.fulfill({
        status: appCalls === 1 ? 503 : 200,
        json:
          appCalls === 1
            ? { message: "Fixture app phase unavailable" }
            : ({
                run_id: appId,
                next_cursor: null,
                counts: { advanced: 1, concurrent_change: 0, incompatible: 0 },
                outcomes: [{ app_id: appId, outcome: "advanced", reason: null }]
              } satisfies Schema<"AppFleetAdvancePublic">),
        headers: sessionResponseHeaders(route)
      });
    });
    try {
      await page.goto(`/spaces/organization/skills/${skill.id}`);
      await page
        .getByRole("button", { name: "Uppdatera alla inaktuella kopplingar", exact: true })
        .click();
      await expect.poll(() => assistantCalls).toBe(1);
      const stop = page.getByRole("button", { name: "Stoppa efter pågående omgång", exact: true });
      await stop.click();
      await expect(stop).toBeDisabled();
      releaseFirst();
      const restart = page.getByRole("button", {
        name: "Försök uppdatera kopplingarna igen",
        exact: true
      });
      await expect(restart).toBeVisible();
      const assistants = page.getByRole("table", { name: "Assistenter", exact: true });
      await expect(
        assistants.getByRole("row", { name: "Läget Vid behov stöds inte 1", exact: true })
      ).toBeVisible();
      await expect(
        assistants.getByRole("row", { name: "För stor kontext 1", exact: true })
      ).toBeVisible();
      await expect(page.getByText("Personlig chatt uppdaterades.", { exact: true })).toBeVisible();
      expect(appCalls).toBe(0);
      await expect(
        page.getByRole("button", { name: "Uppdatera alla inaktuella kopplingar", exact: true })
      ).not.toHaveAttribute("aria-busy", "true");
      await restart.click();
      await expect(page.getByText("Fixture app phase unavailable", { exact: false })).toBeVisible();
      expect(assistantCalls).toBe(2);
      await expect(restart).toBeVisible();
      await expect(restart).not.toHaveAttribute("aria-busy", "true");
      await restart.click();
      await expect(
        page
          .getByRole("table", { name: "Appkopplingar", exact: true })
          .getByRole("row", { name: "Uppdaterade 1", exact: true })
      ).toBeVisible();
      expect(assistantCalls).toBe(2);
      expect(appCalls).toBe(2);
      await expect(
        page.getByText(
          "Körningar som stod i kö före uppdateringen behåller sin tidigare skillversion.",
          { exact: true }
        )
      ).toBeVisible();
      const receipt = page
        .getByRole("heading", { name: "Befintliga kopplingar uppdateras", exact: true })
        .locator("..");
      await expect(receipt.getByText("Uppdateringen är klar", { exact: true })).toHaveCount(3);
      for (const width of [1280, 320]) {
        await page.setViewportSize({ width, height: 900 });
        for (const name of ["Assistenter", "Appkopplingar"]) {
          const bounds = await page.getByRole("table", { name, exact: true }).evaluate((table) => {
            const viewport = table.closest(".astryx-table-scroll-wrapper");
            const count = table.querySelector("thead th:last-child");
            if (!viewport || !count) throw new Error("Missing rollout count column or viewport");
            return {
              countRight: count.getBoundingClientRect().right,
              viewportRight: viewport.getBoundingClientRect().right
            };
          });
          expect(bounds.countRight, `${name} count column at ${width}px`).toBeLessThanOrEqual(
            bounds.viewportRight + 1
          );
        }
        if (width === 320)
          await page
            .getByRole("region", { name: "Assistenter", exact: true })
            .screenshot({ path: testInfo.outputPath("rollout-counts-320.png") });
      }
      await page.setViewportSize({ width: 1280, height: 900 });
      await receipt.scrollIntoViewIfNeeded();
      await receipt.screenshot({ path: testInfo.outputPath("rollout-reasons-resume.png") });
      const search = page.getByRole("searchbox", {
        name: "Sök på resurs, yta eller ägare",
        exact: true
      });
      const searched = page.waitForRequest((request) => {
        const url = new URL(request.url());
        return (
          url.pathname === `/api/v1${path}/adoption/` &&
          url.searchParams.get("query") === "Fixture owner"
        );
      });
      await search.fill("Fixture owner");
      await searched;
      await page.screenshot({
        path: testInfo.outputPath("adoption-live-search.png"),
        fullPage: true
      });
      expect(errors).toEqual([]);
    } finally {
      releaseFirst();
    }
  }
);
