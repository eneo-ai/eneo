// @eneo/ui — Eneo's design system built on shadcn-svelte
// Components are shadcn-svelte open code, themed to match Eneo's design tokens.

// Compound components (use as Alert.Root, Card.Header, etc.)
export * as Alert from "./components/ui/alert";
export * as Card from "./components/ui/card";
export * as Collapsible from "./components/ui/collapsible";
export * as Tabs from "./components/ui/tabs";

// Single components (use directly as <Badge>, <Separator>, <Skeleton>)
export { Badge, badgeVariants, type BadgeVariant } from "./components/ui/badge";
export { Separator } from "./components/ui/separator";
export { Skeleton } from "./components/ui/skeleton";

// Utilities
export { cn, type WithoutChild, type WithoutChildren, type WithoutChildrenOrChild, type WithElementRef } from "./utils";
