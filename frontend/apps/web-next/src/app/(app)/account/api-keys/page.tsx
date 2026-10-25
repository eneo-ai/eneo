import { ApiKeys } from "@/features/api-keys/account-api-keys";
import { pageTitle } from "@/lib/page-metadata";

export const generateMetadata = pageTitle("my_api_keys");

export default function ApiKeysPage() {
  return <ApiKeys />;
}
