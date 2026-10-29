import { pageTitle } from "@/lib/page-metadata";
import { ChangePasswordCard } from "@/features/account/change-password";

export const generateMetadata = pageTitle("change_password");

/** Pushed from Konto: below 1024 px the PageBar names it, so the card gives way (settings-rows). */
export default function AccountPasswordPage() {
  return (
    <div data-pushed-section="">
      <ChangePasswordCard />
    </div>
  );
}
