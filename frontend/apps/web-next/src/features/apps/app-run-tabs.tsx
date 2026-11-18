import { replaceUrl, useSearchParams } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { type App, readAppTab } from "./apps";
import { ResultsTable } from "./results/results-table";
import { RunView } from "./run/run-view";

/**
 * An app's Kör and Resultat tabs, the open one tracked in ?tab=. Shared by the
 * space's app page and the dashboard's; base is the page's own path.
 */
export function AppRunTabs({ app, base }: { app: App; base: string }) {
  const t = useTranslations();
  const searchParams = useSearchParams();
  const tab = readAppTab(searchParams);
  const resultHref = (runId: string) => `${base}/results/${runId}`;

  function selectTab(next: string) {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    replaceUrl(url);
  }

  return (
    <Tabs value={tab} onValueChange={selectTab}>
      <TabsList>
        <TabsTrigger value="run">{t("run")}</TabsTrigger>
        <TabsTrigger value="results">{t("results")}</TabsTrigger>
      </TabsList>
      {/* Kept mounted: a peek at Resultat must not throw away the typed text and delete the uploaded files. */}
      <TabsContent value="run" forceMount className="pt-4 data-[state=inactive]:hidden">
        <RunView app={app} resultHref={resultHref} />
      </TabsContent>
      <TabsContent value="results" className="pt-4">
        <ResultsTable appId={app.id} resultHref={resultHref} />
      </TabsContent>
    </Tabs>
  );
}
