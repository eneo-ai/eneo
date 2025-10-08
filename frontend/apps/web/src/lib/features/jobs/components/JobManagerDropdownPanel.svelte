<script lang="ts">
  import { derived } from "svelte/store";

  import { getJobManager } from "../JobManager";
  import JobListView from "./JobListView.svelte";
  import { ProgressBar } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  const jobManager = getJobManager();
  const {
    state: { uploads, jobs, currentlyRunningJobs }
  } = jobManager;

  const jobsUploadingBlob = derived(jobs, (jobs) => {
    return jobs.filter((job) => job.task === "upload_info_blob");
  });
  const jobsEmbeddingGroup = derived(jobs, (jobs) => {
    return jobs.filter((job) => job.task === "embed_group");
  });
  const jobsTranscribing = derived(jobs, (jobs) => {
    return jobs.filter((job) => job.task === "transcription");
  });
  const jobsCrawling = derived(jobs, (jobs) => {
    return jobs.filter((job) => job.task === "crawl");
  });
  const jobsPullConfluence = derived(jobs, (jobs) => {
    return jobs.filter((job) => job.task === "pull_confluence_content");
  });
  const jobsPullSharepoint = derived(jobs, (jobs) => {
    return jobs.filter((job) => job.task === "pull_sharepoint_content");
  });
</script>

<div class="flex h-full w-full flex-col">
  {#if $uploads.length > 0}
    <div class="border-default flex flex-col gap-1 px-2 py-2">
      <span class="pl-3 font-medium">{m.uploading()}</span>
      <div
        class="border-stronger bg-primary ring-default min-h-10 items-center justify-between rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
      >
        {#each $uploads as upload (upload.id)}
          <div
            class="border-default flex items-center justify-between gap-x-3 border-b px-2 py-1.5 whitespace-nowrap last-of-type:border-b-0"
          >
            <div class="flex-shrink truncate pr-4">{upload.file.name}</div>
            {#if upload.status === "queued"}
              <div class="text-secondary w-48 min-w-48 text-right">{m.waiting()}</div>
            {:else if upload.status === "completed"}
              <div class="text-positive-default w-48 min-w-48 text-right font-medium">{m.done()}</div>
            {:else if true}
              <div class="flex w-48 min-w-48 items-center gap-x-4">
                <ProgressBar progress={upload.progress}></ProgressBar>
                <div class="w-10 text-end">
                  <span class="text-primary text-sm">{upload.progress}%</span>
                </div>
              </div>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {/if}
  <JobListView jobs={$jobsUploadingBlob} title={m.analysing()}></JobListView>
  <JobListView jobs={$jobsEmbeddingGroup} title={m.embedding()}></JobListView>
  <JobListView jobs={$jobsTranscribing} title={m.transcribing()}></JobListView>
  <JobListView jobs={$jobsPullConfluence} title={m.importing_from_confluence()}></JobListView>
  <JobListView jobs={$jobsPullSharepoint} title={m.importing_from_sharepoint()}></JobListView>
  <JobListView jobs={$jobsCrawling} title={m.crawling()}></JobListView>
  {#if $currentlyRunningJobs === 0}
    <div class="text-secondary flex h-[6rem] w-full items-center justify-center">
      <span>{m.everything_up_to_date()}</span>
    </div>
  {/if}
</div>
