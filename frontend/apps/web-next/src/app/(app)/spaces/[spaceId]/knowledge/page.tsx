import { env } from "@/lib/env";
import { pageTitle } from "@/lib/page-metadata";
import { KnowledgePage } from "@/features/knowledge/knowledge-page";

export const generateMetadata = pageTitle("knowledge");

export default function SpaceKnowledgePage() {
  return <KnowledgePage integrationRequestFormUrl={env.REQUEST_INTEGRATION_FORM_URL} />;
}
