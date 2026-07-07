import { KnowledgePage } from "@/features/knowledge/knowledge-page";
import { env } from "@/lib/env";

export default function SpaceKnowledgePage() {
  return <KnowledgePage integrationRequestFormUrl={env.REQUEST_INTEGRATION_FORM_URL} />;
}
