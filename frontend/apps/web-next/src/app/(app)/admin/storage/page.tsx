import { pageTitle } from "@/lib/page-metadata";
import { StorageAdminPage } from "@/features/admin/storage/storage-admin-page";

export const generateMetadata = pageTitle("storage_settings_title");

export default function AdminStorageRoute() {
  return <StorageAdminPage />;
}
