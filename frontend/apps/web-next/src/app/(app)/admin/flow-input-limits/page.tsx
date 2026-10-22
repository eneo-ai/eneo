import { redirect } from "next/navigation";

/** The upload limits' old address (apps/web): they are a group of the flow settings now. */
export default function FlowInputLimitsRoute() {
  redirect("/admin/flow-settings#flow-files");
}
