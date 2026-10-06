import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "next-intl";
import { PublicPage } from "../public-page";

/**
 * The invitation link (`/invite/<organisation>`) explains that invitations
 * are handled on the login page and leads there. The SvelteKit app's page
 * sent the browser to the identity provider's registration; that flow is not
 * ported pending a decision, and this notice is what cannot 404 meanwhile.
 */
export function InviteNotice() {
  const t = useTranslations();

  return (
    <PublicPage
      title={t("invite_title")}
      footer={<Button href="/login" label={t("invite_go_to_login")} variant="primary" />}
    >
      <p className="text-ax-text-secondary text-sm">{t("invite_description")}</p>
    </PublicPage>
  );
}
