import { RuleTester } from "eslint";
import tsParser from "@typescript-eslint/parser";

import rule from "./no-busy-disabled-button.js";

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaFeatures: { jsx: true } },
    sourceType: "module",
  },
});

const LEGACY = 'import { Button } from "@/components/ui/button";\n';
const ASTRYX = 'import { Button } from "@astryxdesign/core/Button";\n';
const ASTRYX_ALIAS =
  'import { Button as AxButton } from "@astryxdesign/core/Button";\n';

const busy = (prop, name) => ({
  messageId: "disabledWhileBusy",
  data: { prop, name },
});
const loading = (prop) => ({ messageId: "loadingDisables", data: { prop } });

ruleTester.run("no-busy-disabled-button", rule, {
  valid: [
    // Busy, the button stays enabled and says so.
    {
      code: `${LEGACY}<Button aria-busy={save.isPending || undefined} onClick={submit} />`,
    },
    {
      code: `${ASTRYX}<Button label={t("save")} isLoading={saving} isInterruptible />`,
    },
    {
      code: `${ASTRYX_ALIAS}<AxButton label={t("save")} isLoading={saving} isInterruptible />`,
    },
    // Gates that are not a pending state.
    {
      code: `${LEGACY}<Button disabled={!canEdit || selected.length === 0} />`,
    },
    { code: `${ASTRYX}<Button label={t("next")} isDisabled={!selectedId} />` },
    // Negated: enabled while busy (the chat composer's send/stop button).
    {
      code: `${ASTRYX}<Button label={t("send")} isDisabled={!busy && !canSubmit} />`,
    },
    // Cancel, Back and Close may wait while the form's action runs.
    {
      code: `${LEGACY}<Button variant="outline" disabled={save.isPending}>{t("cancel")}</Button>`,
    },
    {
      code: `${ASTRYX}<Button label={t("back")} isDisabled={busy} onClick={onBack} />`,
    },
    {
      code: `${LEGACY}<Button disabled={saving}>{t("discard_changes")}</Button>`,
      options: [{ dismissLabels: ["discard_changes"] }],
    },
    // Other components and plain elements are not checked.
    { code: `<button disabled={pending} />` },
    { code: `${LEGACY}<Switch disabled={toggle.isPending} />` },
    {
      code: `import { Button } from "some-other-library";\n<Button disabled={saving} />`,
    },
    // `{ pending: x }` and types name no state.
    { code: `${LEGACY}<Button disabled={isBlocked({ pending: false })} />` },
    { code: `${LEGACY}<Button disabled={(state as PendingState).blocked} />` },
    // isLoading={false} is not loading.
    { code: `${ASTRYX}<Button label={t("save")} isLoading={false} />` },
    // Names come from the option when given.
    {
      code: `${LEGACY}<Button disabled={saving} />`,
      options: [{ names: ["pending"] }],
    },
  ],
  invalid: [
    {
      code: `${LEGACY}<Button disabled={save.isPending} onClick={() => save.mutate()}>{t("save")}</Button>`,
      errors: [busy("disabled", "isPending")],
    },
    {
      code: `${LEGACY}<Button type="submit" disabled={saving}>{saving ? t("saving") : t("save")}</Button>`,
      errors: [busy("disabled", "saving")],
    },
    {
      code: `${LEGACY}<Button disabled={!dirty || busy !== null} />`,
      errors: [busy("disabled", "busy")],
    },
    {
      code: `${LEGACY}<Button disabled={recreate.isPending && renewingId === sub.id} />`,
      errors: [busy("disabled", "isPending")],
    },
    {
      code: `${LEGACY}<Button disabled={skills.isFetchingNextPage}>{t("load_more")}</Button>`,
      errors: [busy("disabled", "isFetchingNextPage")],
    },
    {
      code: `${LEGACY}<Button disabled={!canEdit || upgradeBusy !== null} />`,
      errors: [busy("disabled", "upgradeBusy")],
    },
    {
      code: `${LEGACY}<Button disabled={!(ready && !pending)} />`,
      errors: [busy("disabled", "pending")],
    },
    {
      code: `${ASTRYX}<Button label={t("delete")} isDisabled={deleteSpace.isPending} />`,
      errors: [busy("isDisabled", "isPending")],
    },
    {
      code: `${ASTRYX_ALIAS}<AxButton label={t("tool_accept")} isDisabled={submit.isPending} />`,
      errors: [busy("isDisabled", "isPending")],
    },
    {
      code: `${LEGACY}<Button disabled={uploading || atCapacity} />`,
      errors: [busy("disabled", "uploading")],
    },
    // A label that is not a dismiss key is the action itself.
    {
      code: `${LEGACY}<Button disabled={saving}>{t("reset")}</Button>`,
      errors: [busy("disabled", "saving")],
    },
    // Astryx disables a loading button unless it is interruptible.
    {
      code: `${ASTRYX}<Button type="submit" label={t("create_space")} isLoading={createSpace.isPending} />`,
      errors: [loading("isLoading")],
    },
    {
      code: `${ASTRYX}<Button label={t("save")} clickAction={save} />`,
      errors: [loading("clickAction")],
    },
    {
      code: `${ASTRYX}<Button label={t("save")} isLoading isInterruptible={false} />`,
      errors: [loading("isLoading")],
    },
    // Names come from the option when given.
    {
      code: `${LEGACY}<Button disabled={verifying} />`,
      options: [{ names: ["verifying"] }],
      errors: [busy("disabled", "verifying")],
    },
  ],
});
