import type { Metadata } from "next";

export const metadata: Metadata = {
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    title: "Eneo"
  },
  other: {
    "mobile-web-app-capable": "yes"
  }
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return children;
}
