import { redirect } from "next/navigation";

/** Flow retention's old address (apps/web). This app has no retention settings; the flow settings take its place. */
export default function FlowDataRetentionRoute() {
  redirect("/admin/flow-settings");
}
