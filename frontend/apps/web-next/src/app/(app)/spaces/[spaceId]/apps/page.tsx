import { pageTitle } from "@/lib/page-metadata";
import { AppsPage } from "@/features/apps/apps-page";

export const generateMetadata = pageTitle("apps");

export default function SpaceAppsPage() {
  return <AppsPage />;
}
