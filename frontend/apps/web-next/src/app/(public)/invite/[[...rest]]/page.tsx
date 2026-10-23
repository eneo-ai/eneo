import { pageTitle } from "@/lib/page-metadata";
import { InviteNotice } from "../invite-notice";

export const generateMetadata = pageTitle("invite_title");

/** `/invite` and anything below it (`/invite/<organisationId>`): the notice. */
export default function InvitePage() {
  return <InviteNotice />;
}
