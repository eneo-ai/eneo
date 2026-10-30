import { pageTitle } from "@/lib/page-metadata";
import { AccountAppearance } from "@/features/account/account-appearance";

export const generateMetadata = pageTitle("account_appearance_language");

export default function AccountAppearancePage() {
  return <AccountAppearance />;
}
