import { pageTitle } from "@/lib/page-metadata";
import { ServicesPage } from "@/features/services/services-page";

export const generateMetadata = pageTitle("services");

export default function SpaceServicesPage() {
  return <ServicesPage />;
}
