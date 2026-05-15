import { test } from "vitest";
import type {
  components,
  operations,
  paths
} from "../../../../../../packages/intric-js/src/types/schema";

type AssertTrue<T extends true> = T;
type AssertHasKey<T, _K extends keyof T> = true;

type _CrawlerBaselineResponseExists = AssertTrue<
  components["schemas"]["CrawlerBaselineResponse"] extends object ? true : false
>;
type _CrawlerActiveInventoryResponseExists = AssertTrue<
  components["schemas"]["CrawlerActiveInventoryResponse"] extends object ? true : false
>;
type _CrawlerFailureInventoryResponseExists = AssertTrue<
  components["schemas"]["CrawlerFailureInventoryResponse"] extends object ? true : false
>;
type _CrawlerRecentFailuresResponseExists = AssertTrue<
  components["schemas"]["CrawlerRecentFailuresResponse"] extends object ? true : false
>;
type _CrawlerWatchdogStatusResponseExists = AssertTrue<
  components["schemas"]["CrawlerWatchdogStatusResponse"] extends object ? true : false
>;
type _CrawlerWebsiteProcessingAggregateResponseExists = AssertTrue<
  components["schemas"]["CrawlerWebsiteProcessingAggregateResponse"] extends object ? true : false
>;
type _CrawlerScheduledAggregateResponseExists = AssertTrue<
  components["schemas"]["CrawlerScheduledAggregateResponse"] extends object ? true : false
>;

type _CrawlerBaselineOutcomeCountsField = AssertHasKey<
  components["schemas"]["CrawlerBaselineResponse"],
  "outcome_counts"
>;
type _CrawlerBaselineProcessingTotalsField = AssertHasKey<
  components["schemas"]["CrawlerBaselineResponse"],
  "processing_totals"
>;
type _CrawlerActiveItemsField = AssertHasKey<
  components["schemas"]["CrawlerActiveInventoryResponse"],
  "items"
>;
type _CrawlerActiveLifecycleStateField = AssertHasKey<
  components["schemas"]["CrawlerActiveInventoryItem"],
  "lifecycle_state"
>;
type _CrawlerFailureInventoryItemsField = AssertHasKey<
  components["schemas"]["CrawlerFailureInventoryResponse"],
  "items"
>;
type _CrawlerFailureInventoryStateField = AssertHasKey<
  components["schemas"]["CrawlerFailureInventoryItem"],
  "state"
>;
type _CrawlerRecentFailuresItemsField = AssertHasKey<
  components["schemas"]["CrawlerRecentFailuresResponse"],
  "items"
>;
type _CrawlerRecentFailuresFailureSummaryField = AssertHasKey<
  components["schemas"]["CrawlerRecentFailureItem"],
  "failure_summary"
>;
type _CrawlerWatchdogMetricsField = AssertHasKey<
  components["schemas"]["CrawlerWatchdogStatusResponse"],
  "metrics"
>;
type _CrawlerWatchdogRecentInterventionsField = AssertHasKey<
  components["schemas"]["CrawlerWatchdogStatusResponse"],
  "recent_interventions"
>;
type _CrawlerWebsiteProcessingItemsField = AssertHasKey<
  components["schemas"]["CrawlerWebsiteProcessingAggregateResponse"],
  "items"
>;
type _CrawlerWebsiteProcessingHashRetainedField = AssertHasKey<
  components["schemas"]["CrawlerWebsiteProcessingAggregateItem"],
  "pages_hash_retained"
>;
type _CrawlerScheduledBucketsField = AssertHasKey<
  components["schemas"]["CrawlerScheduledAggregateResponse"],
  "buckets"
>;
type _CrawlerScheduledUpdateIntervalField = AssertHasKey<
  components["schemas"]["CrawlerScheduledIntervalBucket"],
  "update_interval"
>;

type _CrawlerBaselinePathExists = AssertTrue<
  paths["/api/v1/sysadmin/crawler/baseline"]["get"] extends operations["get_crawler_baseline_api_v1_sysadmin_crawler_baseline_get"]
    ? true
    : false
>;
type _CrawlerActivePathExists = AssertTrue<
  paths["/api/v1/sysadmin/crawler/active"]["get"] extends operations["get_crawler_active_inventory_api_v1_sysadmin_crawler_active_get"]
    ? true
    : false
>;
type _CrawlerFailureInventoryPathExists = AssertTrue<
  paths["/api/v1/sysadmin/crawler/failure-inventory"]["get"] extends operations["get_crawler_failure_inventory_api_v1_sysadmin_crawler_failure_inventory_get"]
    ? true
    : false
>;
type _CrawlerRecentFailuresPathExists = AssertTrue<
  paths["/api/v1/sysadmin/crawler/recent-failures"]["get"] extends operations["get_crawler_recent_failures_api_v1_sysadmin_crawler_recent_failures_get"]
    ? true
    : false
>;
type _AdminCrawlerRecentFailuresPathExists = AssertTrue<
  paths["/api/v1/admin/crawler/recent-failures"]["get"] extends operations["get_current_tenant_crawler_recent_failures_api_v1_admin_crawler_recent_failures_get"]
    ? true
    : false
>;
type _AdminCrawlerActivePathExists = AssertTrue<
  paths["/api/v1/admin/crawler/active"]["get"] extends operations["get_current_tenant_crawler_active_inventory_api_v1_admin_crawler_active_get"]
    ? true
    : false
>;
type _AdminCrawlerRecentFailuresQueryHasNoTenantId = AssertTrue<
  "tenant_id" extends keyof NonNullable<
    operations["get_current_tenant_crawler_recent_failures_api_v1_admin_crawler_recent_failures_get"]["parameters"]["query"]
  >
    ? false
    : true
>;
type _AdminCrawlerActiveQueryHasNoTenantId = AssertTrue<
  "tenant_id" extends keyof NonNullable<
    operations["get_current_tenant_crawler_active_inventory_api_v1_admin_crawler_active_get"]["parameters"]["query"]
  >
    ? false
    : true
>;
type _CrawlerWatchdogStatusPathExists = AssertTrue<
  paths["/api/v1/sysadmin/crawler/watchdog-status"]["get"] extends operations["get_crawler_watchdog_status_api_v1_sysadmin_crawler_watchdog_status_get"]
    ? true
    : false
>;
type _CrawlerWebsiteProcessingPathExists = AssertTrue<
  paths["/api/v1/sysadmin/crawler/website-processing"]["get"] extends operations["get_crawler_website_processing_aggregate_api_v1_sysadmin_crawler_website_processing_get"]
    ? true
    : false
>;
type _CrawlerScheduledPathExists = AssertTrue<
  paths["/api/v1/sysadmin/crawler/scheduled"]["get"] extends operations["get_crawler_scheduled_aggregate_api_v1_sysadmin_crawler_scheduled_get"]
    ? true
    : false
>;

test.todo("crawler sysadmin generated API contract is enforced by type assertions");
