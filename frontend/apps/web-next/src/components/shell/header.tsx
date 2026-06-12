import Link from "next/link";
import { MainNav } from "@/components/shell/main-nav";
import { ProfileMenu } from "@/components/shell/profile-menu";
import { ThemeSwitcher } from "@/components/shell/theme-switcher";

export function Header() {
  return (
    <header className="bg-background sticky top-0 z-10 flex h-14 items-center gap-4 border-b px-4">
      <Link href="/" className="text-lg font-semibold">
        Eneo
      </Link>
      <MainNav />
      <ThemeSwitcher />
      <ProfileMenu />
    </header>
  );
}
