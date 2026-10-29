import { AccountFrame } from "@/features/account/account-frame";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("my_account");

export default function AccountLayout({ children }: { children: React.ReactNode }) {
  return <AccountFrame>{children}</AccountFrame>;
}
