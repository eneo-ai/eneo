import { getTranslations } from "next-intl/server";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { pageTitle } from "@/lib/page-metadata";
import { CopyFormatChoice } from "../copy-format.client";

export const generateMetadata = pageTitle("account_copy_format");

/** Pushed from Konto: below 1024 px the PageBar names it, so the card gives way (settings-rows). */
export default async function AccountCopyFormatPage() {
  const t = await getTranslations();
  return (
    <div data-pushed-section="">
      <SettingsGroup title={t("account_copy_format")}>
        <SettingsRow
          title={t("preferred_copy_format")}
          description={t("preferred_copy_format_description")}
        >
          <CopyFormatChoice />
        </SettingsRow>
      </SettingsGroup>
    </div>
  );
}
