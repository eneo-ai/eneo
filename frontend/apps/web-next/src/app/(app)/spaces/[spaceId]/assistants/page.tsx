import { pageTitle } from "@/lib/page-metadata";
import { AssistantsPage } from "@/features/assistants/assistants-page";

export const generateMetadata = pageTitle("assistants");

export default function SpaceAssistantsPage() {
  return <AssistantsPage />;
}
