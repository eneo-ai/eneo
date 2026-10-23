import { pageTitle } from "@/lib/page-metadata";
import { CrawlerPage } from "@/features/admin/crawler/crawler-page";

export const generateMetadata = pageTitle("admin_crawler_title");

export default function AdminCrawlerPage() {
  return <CrawlerPage />;
}
