import { createFileRoute, redirect } from "@tanstack/react-router";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";

export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/$", params: { _splat: DEFAULT_LANDING.slice(1) }, replace: true });
  }
});
