import { redirect } from "next/navigation";

export default function RootPage() {
  // Parity target is /spaces/personal/chat (DEFAULT_LANDING_PAGE in the
  // Svelte app); switches over when Phase 5 ships the chat surface.
  redirect("/dashboard");
}
