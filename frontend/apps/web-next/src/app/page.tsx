import { redirect } from "next/navigation";

export default function RootPage() {
  // DEFAULT_LANDING_PAGE parity with the Svelte app.
  redirect("/spaces/personal/chat");
}
