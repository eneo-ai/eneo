import { createRootRoute, Outlet } from "@tanstack/react-router";

// Stub so the Vite build has a route tree; P4-router-core replaces it.
export const Route = createRootRoute({ component: Outlet });
