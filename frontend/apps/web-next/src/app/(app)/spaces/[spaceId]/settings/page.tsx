import { pageTitle } from "@/lib/page-metadata";
import { SpaceSettings } from "@/features/spaces/settings/space-settings";

export const generateMetadata = pageTitle("settings");

export default function SpaceSettingsPage() {
  return <SpaceSettings />;
}
