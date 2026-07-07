import Link from "next/link";
import { EneoIcon, EneoWordMark } from "@/components/shell/eneo-logo";
import { MainNav } from "@/components/shell/main-nav";
import { ProfileMenu } from "@/components/shell/profile-menu";
import { ThemeSwitcher } from "@/components/shell/theme-switcher";
import { ExpiringKeysNotification } from "@/features/api-keys/expiring-keys-notification";
import { JobIndicator } from "@/features/jobs/job-indicator";

export function Header() {
  return (
    <header className="bg-background/85 sticky top-0 z-10 flex h-14 items-center gap-4 border-b px-4 backdrop-blur-md">
      <Link href="/" className="text-foreground flex items-center">
        <EneoWordMark className="hidden h-7 w-auto md:block" />
        <EneoIcon className="block h-7 w-auto md:hidden" />
      </Link>
      <MainNav />
      <JobIndicator />
      <ExpiringKeysNotification />
      <ThemeSwitcher />
      <ProfileMenu />
    </header>
  );
}
