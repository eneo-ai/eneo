import { AccountProfile } from "./account-profile.client";
import { ChangePasswordCard } from "./change-password.client";

export default function AccountPage() {
  return (
    <div className="flex flex-col gap-6">
      <AccountProfile />
      <ChangePasswordCard />
    </div>
  );
}
