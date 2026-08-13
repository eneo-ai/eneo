import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import SkillForm from "./SkillForm.svelte";

describe("SkillForm", () => {
  test("owns blank-submit validation and focuses the first invalid field", async () => {
    const onSubmit = vi.fn();
    render(SkillForm, { mode: "create", onSubmit });

    await page.getByRole("button", { name: m.skills_create_action() }).click();

    const nameInput = page.getByLabelText(m.skills_display_name_label());
    await expect.element(nameInput).toHaveFocus();
    await expect.element(nameInput).toHaveAttribute("aria-invalid", "true");
    await expect
      .element(page.getByLabelText(m.skills_description_label()))
      .toHaveAttribute("aria-invalid", "true");
    await expect
      .element(page.getByLabelText(m.skills_instructions_label()))
      .toHaveAttribute("aria-invalid", "true");
    await expect.element(page.getByText(m.skills_required_field()).first()).toBeVisible();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("reveals and focuses a derived empty identifier after submit", async () => {
    const onSubmit = vi.fn();
    render(SkillForm, { mode: "create", onSubmit });

    await page.getByLabelText(m.skills_display_name_label()).fill("能力");
    await page.getByLabelText(m.skills_description_label()).fill("Focused support.");
    await page.getByLabelText(m.skills_instructions_label()).fill("Use approved sources.");
    await page.getByRole("button", { name: m.skills_create_action() }).click();

    const slugInput = page.getByLabelText(m.skills_slug_label());
    await expect.element(slugInput).toBeVisible();
    await expect.element(slugInput).toHaveFocus();
    await expect.element(slugInput).toHaveAttribute("aria-invalid", "true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("reopens and focuses a cleared identifier after Advanced is collapsed", async () => {
    const onSubmit = vi.fn();
    render(SkillForm, { mode: "create", onSubmit });

    await page.getByLabelText(m.skills_display_name_label()).fill("HR support");
    await page.getByLabelText(m.skills_description_label()).fill("Focused support.");
    await page.getByLabelText(m.skills_instructions_label()).fill("Use approved sources.");
    const advancedButton = page.getByRole("button", { name: m.skills_advanced_options() });
    await advancedButton.click();
    await page.getByLabelText(m.skills_slug_label()).fill("");
    await advancedButton.click();
    await page.getByRole("button", { name: m.skills_create_action() }).click();

    const slugInput = page.getByLabelText(m.skills_slug_label());
    await expect.element(slugInput).toBeVisible();
    await expect.element(slugInput).toHaveFocus();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("reports dirtiness and explicitly discards back to its baseline", async () => {
    const onDirtyChange = vi.fn();
    render(SkillForm, {
      mode: "create",
      showDiscardAction: true,
      onDirtyChange,
      onSubmit: vi.fn()
    });

    const nameInput = page.getByLabelText(m.skills_display_name_label());
    await nameInput.fill("HR support");
    const discardButton = page.getByRole("button", { name: m.discard_all_changes() });
    await expect.element(discardButton).toBeVisible();
    await expect.element(page.getByText(m.skills_form_unsaved_status())).toBeVisible();
    await vi.waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(true));

    await discardButton.click();

    await expect.element(nameInput).toHaveValue("");
    await expect.element(discardButton).not.toBeInTheDocument();
    await vi.waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false));
  });

  test("derives an editable create-only identifier and preserves values after failure", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("Failed"));
    render(SkillForm, { mode: "create", onSubmit });

    const nameInput = page.getByLabelText(m.skills_display_name_label());
    const descriptionInput = page.getByLabelText(m.skills_description_label());
    const instructionsInput = page.getByLabelText(m.skills_instructions_label());

    await nameInput.fill("Lön och frånvaro");
    await descriptionInput.fill("Hjälper till med frågor om lön och frånvaro.");
    await instructionsInput.fill("## Uppgift\n\nBesvara frågan med stöd i källorna.");
    await page.getByRole("button", { name: m.skills_advanced_options() }).click();

    const slugInput = page.getByLabelText(m.skills_slug_label());
    await expect.element(slugInput).toHaveValue("lon-och-franvaro");
    await slugInput.fill("hr-support");
    await page.getByRole("button", { name: m.skills_create_action() }).click();

    await expect.element(page.getByText(m.skills_form_error_title())).toBeVisible();
    await expect.element(nameInput).toHaveValue("Lön och frånvaro");
    await expect
      .element(descriptionInput)
      .toHaveValue("Hjälper till med frågor om lön och frånvaro.");
    await expect
      .element(instructionsInput)
      .toHaveValue("## Uppgift\n\nBesvara frågan med stöd i källorna.");
    await expect.element(slugInput).toHaveValue("hr-support");
    expect(onSubmit).toHaveBeenCalledWith({
      display_name: "Lön och frånvaro",
      description: "Hjälper till med frågor om lön och frånvaro.",
      instructions: "## Uppgift\n\nBesvara frågan med stöd i källorna.",
      slug: "hr-support"
    });

    expect((nameInput.element() as HTMLInputElement).maxLength).toBe(200);
    expect((descriptionInput.element() as HTMLTextAreaElement).maxLength).toBe(1024);
    expect((instructionsInput.element() as HTMLTextAreaElement).maxLength).toBe(-1);
    expect((slugInput.element() as HTMLInputElement).maxLength).toBe(64);
  });

  test("hides the stable identifier in revision mode and uses its custom pending label", async () => {
    let finishSubmit: (() => void) | undefined;
    const onSubmit = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishSubmit = resolve;
        })
    );
    render(SkillForm, {
      mode: "revision",
      initialValue: {
        display_name: "HR support",
        description: "Answers focused HR questions.",
        instructions: "Answer using approved sources."
      },
      submitLabel: "Save revision",
      submittingLabel: "Saving revision…",
      onSubmit
    });

    await expect
      .element(page.getByRole("button", { name: m.skills_advanced_options() }))
      .not.toBeInTheDocument();
    await expect.element(page.getByLabelText(m.skills_slug_label())).not.toBeInTheDocument();

    await page.getByRole("button", { name: "Save revision" }).click();
    await expect.element(page.getByRole("button", { name: "Saving revision…" })).toBeDisabled();
    expect(onSubmit).toHaveBeenCalledWith({
      display_name: "HR support",
      description: "Answers focused HR questions.",
      instructions: "Answer using approved sources."
    });

    finishSubmit?.();
    await expect.element(page.getByRole("button", { name: "Save revision" })).toBeEnabled();
    await expect.element(page.getByText(m.skills_form_saved_status())).toBeVisible();
  });
});
