import { redirect } from "next/navigation";

/** The saved source text's old address (apps/web): it is a group of the flow settings now. */
export default function FlowKnowledgeEvidenceRoute() {
  redirect("/admin/flow-settings#flow-evidence-text");
}
