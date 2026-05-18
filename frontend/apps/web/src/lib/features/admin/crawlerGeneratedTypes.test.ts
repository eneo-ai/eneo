import { test } from "vitest";
import type {
  components,
  operations,
  paths
} from "../../../../../../packages/intric-js/src/types/schema";

type AssertTrue<T extends true> = T;
type AssertHasKey<T, _K extends keyof T> = true;
type AssertNoKey<T, K extends PropertyKey> = K extends keyof T ? false : true;

type _CrawlerBaselineResponseExists = AssertTrue<
  components["schemas"]["CrawlerBaselineResponse"] extends object ? true : false
>;
type _CrawlerActiveInventoryResponseExists = AssertTrue<
  components["schemas"]["CrawlerActiveInventoryResponse"] extends object ? true : false
>;
type _CrawlerFailureInventoryResponseExists = AssertTrue<
  components["schemas"]["CrawlerFailureInventoryResponse"] extends object ? true : false
>;
type _CrawlerTenantFailureInventoryResponseExists = AssertTrue<
  components["schemas"]["CrawlerTenantFailureInventoryResponse"] extends object ? true : false
>;
type _CrawlerRecentFailuresResponseExists = AssertTrue<
  components["schemas"]["CrawlerRecentFailuresResponse"] extends object ? true : false
>;
type _CrawlerFailureClustersResponseExists = AssertTrue<
  components["schemas"]["CrawlerFailureClustersResponse"] extends object ? true : false
>;
type _CrawlerWatchdogStatusResponseExists = AssertTrue<
  components["schemas"]["CrawlerWatchdogStatusResponse"] extends object ? true : false
>;
type _CrawlerWebsiteProcessingAggregateResponseExists = AssertTrue<
  components["schemas"]["CrawlerWebsiteProcessingAggregateResponse"] extends object ? true : false
>;
type _CrawlerTenantWebsiteProcessingAggregateResponseExists = AssertTrue<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateResponse"] extends object
    ? true
    : false
>;
type _CrawlerScheduledAggregateResponseExists = AssertTrue<
  components["schemas"]["CrawlerScheduledAggregateResponse"] extends object ? true : false
>;
type _CrawlerAbortConflictResponseExists = AssertTrue<
  components["schemas"]["CrawlerAbortConflictResponse"] extends object ? true : false
>;
type _CrawlFileTooLargeSamplePublicExists = AssertTrue<
  components["schemas"]["CrawlFileTooLargeSamplePublic"] extends object ? true : false
>;

type _CrawlerBaselineOutcomeCountsField = AssertHasKey<
  components["schemas"]["CrawlerBaselineResponse"],
  "outcome_counts"
>;
type _CrawlerBaselineProcessingTotalsField = AssertHasKey<
  components["schemas"]["CrawlerBaselineResponse"],
  "processing_totals"
>;
type _CrawlerBaselineEmbeddingTokensField = AssertHasKey<
  components["schemas"]["CrawlerBaselineProcessingTotals"],
  "embedding_input_tokens"
>;
type _CrawlerBaselineEmbeddingCostField = AssertHasKey<
  components["schemas"]["CrawlerBaselineProcessingTotals"],
  "embedding_total_cost_usd"
>;
type _CrawlerActiveItemsField = AssertHasKey<
  components["schemas"]["CrawlerActiveInventoryResponse"],
  "items"
>;
type _CrawlerActiveLifecycleStateField = AssertHasKey<
  components["schemas"]["CrawlerActiveInventoryItem"],
  "lifecycle_state"
>;
type _CrawlerActiveIsAbortableField = AssertHasKey<
  components["schemas"]["CrawlerActiveInventoryItem"],
  "is_abortable"
>;
type _CrawlerFailureInventoryItemsField = AssertHasKey<
  components["schemas"]["CrawlerFailureInventoryResponse"],
  "items"
>;
type _CrawlerFailureInventoryStateField = AssertHasKey<
  components["schemas"]["CrawlerFailureInventoryItem"],
  "state"
>;
type _CrawlerTenantFailureInventoryItemsField = AssertHasKey<
  components["schemas"]["CrawlerTenantFailureInventoryResponse"],
  "items"
>;
type _CrawlerTenantFailureInventoryStateField = AssertHasKey<
  components["schemas"]["CrawlerTenantFailureInventoryItem"],
  "state"
>;
type _CrawlerTenantFailureInventorySpaceNameField = AssertHasKey<
  components["schemas"]["CrawlerTenantFailureInventoryItem"],
  "space_name"
>;
type _CrawlerTenantFailureInventoryOwnerEmailField = AssertHasKey<
  components["schemas"]["CrawlerTenantFailureInventoryItem"],
  "owner_email"
>;
type _CrawlerTenantFailureInventoryLatestFailureField = AssertHasKey<
  components["schemas"]["CrawlerTenantFailureInventoryItem"],
  "latest_failure_outcome_code"
>;
type _CrawlerRecentFailuresItemsField = AssertHasKey<
  components["schemas"]["CrawlerRecentFailuresResponse"],
  "items"
>;
type _CrawlerRecentFailuresFailureSummaryField = AssertHasKey<
  components["schemas"]["CrawlerRecentFailureItem"],
  "failure_summary"
>;
type _CrawlerRecentFailuresEmbeddingTokensField = AssertHasKey<
  components["schemas"]["CrawlerRecentFailureItem"],
  "embedding_input_tokens"
>;
type _CrawlerRecentFailuresEmbeddingModelField = AssertHasKey<
  components["schemas"]["CrawlerRecentFailureItem"],
  "embedding_model_name_snapshot"
>;
type _CrawlerFailureClustersItemsField = AssertHasKey<
  components["schemas"]["CrawlerFailureClustersResponse"],
  "items"
>;
type _CrawlerFailureClustersSourceField = AssertHasKey<
  components["schemas"]["CrawlerFailureClustersResponse"],
  "source"
>;
type _CrawlerFailureClusterCategoryField = AssertHasKey<
  components["schemas"]["CrawlerFailureClusterItem"],
  "outcome_category"
>;
type _CrawlerFailureClusterOwnerEmailField = AssertHasKey<
  components["schemas"]["CrawlerFailureClusterItem"],
  "owner_email"
>;
type _CrawlerFailureClusterOccurrencesField = AssertHasKey<
  components["schemas"]["CrawlerFailureClusterItem"],
  "occurrences"
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
type _CrawlerWebsiteProcessingCostPressureField = AssertHasKey<
  components["schemas"]["CrawlerWebsiteProcessingAggregateItem"],
  "cost_pressure_score"
>;
type _CrawlerWebsiteProcessingRetentionRateField = AssertHasKey<
  components["schemas"]["CrawlerWebsiteProcessingAggregateItem"],
  "retention_rate"
>;
type _CrawlerTenantWebsiteProcessingItemsField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateResponse"],
  "items"
>;
type _CrawlerTenantWebsiteProcessingTooLargeField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "files_too_large_skipped"
>;
type _CrawlerTenantWebsiteProcessingWebsiteUrlField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "website_url"
>;
type _CrawlerTenantWebsiteProcessingSpaceNameField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "space_name"
>;
type _CrawlerTenantWebsiteProcessingOwnerEmailField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "owner_email"
>;
type _CrawlerTenantWebsiteProcessingIndexedSizeField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "indexed_size_bytes"
>;
type _CrawlerTenantWebsiteProcessingSummaryField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateResponse"],
  "summary"
>;
type _CrawlerTenantWebsiteProcessingNoTenantTotalStorage = AssertTrue<
  AssertNoKey<
    components["schemas"]["CrawlerTenantWebsiteProcessingAggregateResponse"],
    "tenant_total_storage_bytes"
  >
>;
type _CrawlerTenantWebsiteProcessingNoTenantTotalTokens = AssertTrue<
  AssertNoKey<
    components["schemas"]["CrawlerTenantWebsiteProcessingAggregateResponse"],
    "tenant_total_tokens"
  >
>;
type _CrawlerTenantWebsiteProcessingSpaceRollupField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateResponse"],
  "space_rollup"
>;
type _CrawlerTenantWebsiteProcessingSummaryActionCountField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateSummary"],
  "action_required_count"
>;
type _CrawlerTenantWebsiteProcessingSpaceRollupWebsiteCountField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingSpaceRollupItem"],
  "website_count"
>;
type _CrawlerTenantWebsiteProcessingSpaceRollupTokensField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingSpaceRollupItem"],
  "embedding_input_tokens"
>;
type _CrawlerTenantWebsiteProcessingCostPressureField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "cost_pressure_score"
>;
type _CrawlerTenantWebsiteProcessingUpdateIntervalField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "update_interval"
>;
type _CrawlerTenantWebsiteProcessingEmbeddingTokensField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "embedding_input_tokens"
>;
type _CrawlerTenantWebsiteProcessingEmbeddingCostField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "embedding_total_cost_usd"
>;
type _CrawlerTenantWebsiteProcessingLatestEmbeddingModelField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "latest_embedding_model_name_snapshot"
>;
type _CrawlerTenantWebsiteProcessingLatestEmbeddingTokensField = AssertHasKey<
  components["schemas"]["CrawlerTenantWebsiteProcessingAggregateItem"],
  "latest_embedding_input_tokens"
>;
type _CrawlerScheduledBucketsField = AssertHasKey<
  components["schemas"]["CrawlerScheduledAggregateResponse"],
  "buckets"
>;
type _CrawlerScheduledUpdateIntervalField = AssertHasKey<
  components["schemas"]["CrawlerScheduledIntervalBucket"],
  "update_interval"
>;
type _CrawlRunTooLargeLimitField = AssertHasKey<
  components["schemas"]["intric__websites__presentation__website_models__CrawlRunPublic"],
  "files_too_large_download_limit_bytes"
>;
type _CrawlRunTooLargeSamplesField = AssertHasKey<
  components["schemas"]["intric__websites__presentation__website_models__CrawlRunPublic"],
  "files_too_large_samples"
>;
type _CrawlFileTooLargeSampleObservedBytesField = AssertHasKey<
  components["schemas"]["CrawlFileTooLargeSamplePublic"],
  "observed_size_bytes"
>;
type _CrawlOutcomeSamplesFieldRemoved = AssertTrue<
  AssertNoKey<components["schemas"]["CrawlOutcomePublic"], "samples">
>;
type _TokenUsageSourceBreakdownField = AssertHasKey<
  components["schemas"]["TokenUsageSummary"],
  "source_breakdown"
>;
type _TokenUsageTotalCostField = AssertHasKey<
  components["schemas"]["TokenUsageSummary"],
  "total_cost_usd"
>;
type _TokenUsageCostCoverageField = AssertHasKey<
  components["schemas"]["TokenUsageSummary"],
  "cost_coverage_ratio"
>;
type _ModelUsageSourceTypesField = AssertHasKey<
  components["schemas"]["ModelUsage"],
  "source_types"
>;
type _ModelUsageModelKindField = AssertHasKey<components["schemas"]["ModelUsage"], "model_kind">;
type _ModelUsageNullableModelId = AssertTrue<
  components["schemas"]["ModelUsage"]["model_id"] extends string | null ? true : false
>;
type _SourceUsageExists = AssertTrue<
  components["schemas"]["SourceUsage"] extends object ? true : false
>;
type _TokenUsageModelHasNoWebsiteId = AssertTrue<
  AssertNoKey<components["schemas"]["ModelUsage"], "website_id">
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
type _AdminCrawlerWatchdogInterventionsPathExists = AssertTrue<
  paths["/api/v1/admin/crawler/watchdog-interventions"]["get"] extends operations["get_current_tenant_crawler_watchdog_interventions_api_v1_admin_crawler_watchdog_interventions_get"]
    ? true
    : false
>;
type _AdminCrawlerFailureClustersPathExists = AssertTrue<
  paths["/api/v1/admin/crawler/failure-clusters"]["get"] extends operations["get_current_tenant_crawler_failure_clusters_api_v1_admin_crawler_failure_clusters_get"]
    ? true
    : false
>;
type _AdminCrawlerActivePathExists = AssertTrue<
  paths["/api/v1/admin/crawler/active"]["get"] extends operations["get_current_tenant_crawler_active_inventory_api_v1_admin_crawler_active_get"]
    ? true
    : false
>;
type _AdminCrawlerFailureInventoryPathExists = AssertTrue<
  paths["/api/v1/admin/crawler/failure-inventory"]["get"] extends operations["get_current_tenant_crawler_failure_inventory_api_v1_admin_crawler_failure_inventory_get"]
    ? true
    : false
>;
type _AdminCrawlerScheduledPathExists = AssertTrue<
  paths["/api/v1/admin/crawler/scheduled"]["get"] extends operations["get_current_tenant_crawler_scheduled_aggregate_api_v1_admin_crawler_scheduled_get"]
    ? true
    : false
>;
type _AdminCrawlerWebsiteProcessingPathExists = AssertTrue<
  paths["/api/v1/admin/crawler/website-processing"]["get"] extends operations["get_current_tenant_crawler_website_processing_aggregate_api_v1_admin_crawler_website_processing_get"]
    ? true
    : false
>;
type _AdminCrawlerAbortQueuedPathExists = AssertTrue<
  paths["/api/v1/admin/crawler/jobs/{job_id}/abort"]["post"] extends operations["abort_current_tenant_queued_crawl_api_v1_admin_crawler_jobs__job_id__abort_post"]
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
type _AdminCrawlerWatchdogInterventionsQueryHasNoTenantId = AssertTrue<
  "tenant_id" extends keyof NonNullable<
    operations["get_current_tenant_crawler_watchdog_interventions_api_v1_admin_crawler_watchdog_interventions_get"]["parameters"]["query"]
  >
    ? false
    : true
>;
type _AdminCrawlerFailureClustersQueryHasNoTenantId = AssertTrue<
  "tenant_id" extends keyof NonNullable<
    operations["get_current_tenant_crawler_failure_clusters_api_v1_admin_crawler_failure_clusters_get"]["parameters"]["query"]
  >
    ? false
    : true
>;
type _AdminCrawlerFailureClustersQueryHasSource = AssertHasKey<
  NonNullable<
    operations["get_current_tenant_crawler_failure_clusters_api_v1_admin_crawler_failure_clusters_get"]["parameters"]["query"]
  >,
  "source"
>;
type _AdminCrawlerActiveQueryHasNoTenantId = AssertTrue<
  "tenant_id" extends keyof NonNullable<
    operations["get_current_tenant_crawler_active_inventory_api_v1_admin_crawler_active_get"]["parameters"]["query"]
  >
    ? false
    : true
>;
type _AdminCrawlerFailureInventoryQueryHasNoTenantId = AssertTrue<
  "tenant_id" extends keyof NonNullable<
    operations["get_current_tenant_crawler_failure_inventory_api_v1_admin_crawler_failure_inventory_get"]["parameters"]["query"]
  >
    ? false
    : true
>;
type _AdminCrawlerScheduledQueryIsEmpty = AssertTrue<
  NonNullable<
    operations["get_current_tenant_crawler_scheduled_aggregate_api_v1_admin_crawler_scheduled_get"]["parameters"]["query"]
  > extends never
    ? true
    : false
>;
type _AdminCrawlerWebsiteProcessingQueryHasNoTenantId = AssertTrue<
  "tenant_id" extends keyof NonNullable<
    operations["get_current_tenant_crawler_website_processing_aggregate_api_v1_admin_crawler_website_processing_get"]["parameters"]["query"]
  >
    ? false
    : true
>;
type _AdminCrawlerWebsiteProcessingQueryHasSpaceId = AssertHasKey<
  NonNullable<
    operations["get_current_tenant_crawler_website_processing_aggregate_api_v1_admin_crawler_website_processing_get"]["parameters"]["query"]
  >,
  "space_id"
>;
type _AdminCrawlerAbortQueuedPathHasJobId = AssertHasKey<
  NonNullable<
    operations["abort_current_tenant_queued_crawl_api_v1_admin_crawler_jobs__job_id__abort_post"]["parameters"]["path"]
  >,
  "job_id"
>;
type _AdminCrawlerAbortQueuedQueryIsEmpty = AssertTrue<
  NonNullable<
    operations["abort_current_tenant_queued_crawl_api_v1_admin_crawler_jobs__job_id__abort_post"]["parameters"]["query"]
  > extends never
    ? true
    : false
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
