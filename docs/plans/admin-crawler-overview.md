# Crawleröversikt i adminpanelen

Genomförd första version, 9 september 2026. Arbetet följs i Beads `crawl-f35` i
`crawler-review`. Sidan blir tillgänglig när backend, databas och frontend har
uppdaterats tillsammans.

Administratören kan se vad som körs i hela tenanten, vad som väntar och
vilka körningar som har fått fel. Sidan placeras på `/admin/crawler`, under
adminmenyns befintliga grupp för analys och loggar, med namnet **Crawler**.

## Sidans innehåll

Överst visas tre kompakta sammanfattningar. De omfattar hela tenanten, oavsett
vilken del av tabellen som har laddats eller filtrerats.

| Sammanfattning | Betydelse |
| --- | --- |
| Pågående | Körningar i `running`, `finalizing` eller `stopping` just nu. |
| I kö | Körningar i `pending_dispatch` eller `queued` just nu. |
| Fel och varningar, senaste 24 timmarna | Avslutade körningar med `partial`, `failed` eller `interrupted`. Användaravbrott räknas inte som fel. |

Under sammanfattningen finns två flikar: **Aktiva** som standard och **Senaste
dygnet**. Aktiva innehåller både pågående och köade körningar. Dygnsvyn visar
avslutade körningar, med senast avslutad först. Det går att filtrera på status
och söka efter webbplatsens namn eller adress. Sammanfattningen för fel och
varningar öppnar motsvarande filter i dygnsvyn. Historiska fel ligger kvar där
även om en senare körning har lyckats.

Tabellen har en rad per körning:

| Information | Visning |
| --- | --- |
| Webbplats | Namn och adress. En tydlig knapp på namnet öppnar körningsdetaljer. |
| Yta | Ytans namn så att samma webbplats i olika ytor går att skilja åt. |
| Status | Befintliga översatta statusetiketter. Köad, pågår, slutförs och stoppas går att skilja åt. |
| Resultat | Antal indexerade sidor och filer samt misslyckade resurser när sådana finns. Okända räknare visas som okända. |
| Tid | Väntetid för köade körningar; start och varaktighet för körningar som har startat. |
| Senast indexerad | Webbplatsens befintliga tidsstämpel, som bevaras vid ett senare fel. |

Aktiva körningar sorteras med äldst accepterad först, så att långa väntetider
syns. Skapandetid och verklig starttid hålls isär. Det finns inget känt totalantal
för alla crawls, så sidan visar räknare utan uppskattad procent eller sluttid.
En lång körning får inte automatiskt etiketten ”fastnad”.

Ett klick öppnar den befintliga detaljvyn för körningen: resultat, översatt
felorsak och sidvis hämtade feladresser. Där hör också manuell/schemalagd start
hemma. Äldre körningar kan sakna adressdetaljer. Översikten länkar inte vidare till webbplatsens kunskapssida, eftersom
adminbehörighet i sig inte ger åtkomst till den ytan.

## Shadcn och uppdatering

Sidan använder projektets installerade **shadcn-svelte, Nova**, adminlayout och
semantiska färger. `Card` visar de tre sammanfattningarna, `Tabs` vyerna,
`Table` körningarna, `Badge` status och `Input`/`Select` filtreringen. Den använder befintlig `Dialog` för körningsdetaljer. Ingen ny komponentfamilj behövs.

Sidan uppdateras var tionde sekund medan sidan är synlig, med högst en pågående
uppdatering. Filter och befintliga rader behålls under uppdateringen. Sidan visar
”Senast hämtat” och en manuell uppdateringsknapp. Vid fel behålls senaste
resultatet med ett tydligt felbesked och möjlighet att försöka igen. Noll
aktiva körningar ska vara ett begripligt normaltillstånd. Skeleton används vid
första laddningen. Tangentbord, fokus, svenska/engelska och smala skärmar ska
fungera med de befintliga komponenterna.

Första versionen är en läsvy. Start/stopp för hela tenanten, crawlerinställningar,
grafer, kostnadsberäkningar och aviseringar ingår inte.

## Behörighet och data

Använd samma `admin`-behörighet som resten av adminpanelen; den ingår i den
fördefinierade rollen Owner. Skydda både sidan och backendmetoderna. Tenantens
identitet hämtas från den autentiserade användaren, aldrig från ett valbart
tenant-id i klienten. Befintliga krav på API-nycklars adminomfattning gäller även
här. Inga nya behörigheter eller rollnamnsjämförelser behövs.

Owner har inte automatiskt läsrätt till alla privata ytor. Tenantöversikten
behöver därför en uttrycklig adminläsning av körningsmetadata och feladresser,
även för dessa ytor. Den läsningen ger inte nya rättigheter till indexerat
innehåll, privata dokument eller ändringar av webbplatsen. Behörigheten till den
vanliga kunskapssidan fortsätter att prövas som tidigare.

API-ytan består av en adminendpoint för sammanfattning och en begränsad sida
med körningar, samt en adminendpoint för vald körnings feladresser. Båda ligger
under `/api/v1/admin/crawler/`. Befintliga svarstyper för körningar och fel används
inne i projektionen; klienttyper genereras från OpenAPI. Detaljvyn återanvänds
med rätt hämtfunktion för respektive behörighetskontext.

Läsningen ägs av befintlig `CrawlRunRepository` och använder adminpanelens
behörighetskontroll. Läs enbart nödvändiga fält från körningar, aktuellt försök,
webbplatser och ytor. Hämta inte alla ytors innehåll eller alla jobb till
webbläsaren. Begränsa varje sida till högst 100 rader och använd stabil cursor
med tidsstämpel och id. Dygnsvyn avgränsas av avslutningstid; sammanfattningens
tidpunkt returneras så att siffrorna går att tolka.

`CrawlRuns`, `CrawlAttempts`, `CrawlRunFailures` och `Websites.last_indexed_at`
innehåller underlaget. Jobblistan är användarspecifik och den befintliga
hälsosammanfattningen gäller hela installationen; ingen av dem kan användas
direkt som tenantöversikt. Nya statuslager, köer, summeringstabeller och ändringar
av crawlerns körning behövs inte. Historikfrågorna använder ett partiellt index på tenant, avslutningstid och id
för avslutade körningar. Det befintliga indexet för aktiva körningar återanvänds.

## Verifiering och drift

Verifieringen omfattar 80 PostgreSQL-integrationstester för adminåtkomst,
körningshistorik och crawlerns körningsflöde, åtta migrationstester och 37
frontendtester för översikten, adminmenyn och statuspresentationen. Testerna
kontrollerar tenantisolering, privata ytors innehållsrättigheter, köstatus,
dygnsgräns, cursor, samtidig filtrering och hämtning samt återhämtning efter
nätverksfel. API-kontrakt, strikta typer och språknycklar har kontrollerats.
Sidan har också granskats visuellt i ljust och mörkt tema, vid bred, mellanbred
och smal skärm samt med öppen detaljdialog.

En lokal frågeplansmätning använde 100 000 äldre avslutade körningar utan aktiva
körningar eller resultat från senaste dygnet. Med historikindexet gick de två
SQL-frågorna från 7,617/5,123 ms till 0,014/0,017 ms, med 3–4 bufferträffar i
stället för 1 819. Detta visar att tomma aktuella vyer kan hoppa över gammal
historik; det är ingen mätning av produktionslatens eller hela HTTP-anropet.

Migration `202609091600` skapar historikindexet med `CREATE INDEX CONCURRENTLY`.
Ett avbrutet indexbygge kan lämna ett ogiltigt index; en ny uppgradering tar bort
det och bygger om det. Nedgradering tar bort indexet i samma transaktion som
övrig återställning, så att befintliga spärrar för aktiva körningar eller sparade
feladresser inte lämnar schemat delvis ändrat.

Separat rättar `crawl-wk9` ett fel där dokumentextraktionens resursgräns följdes
av `KeyError: Attempt to overwrite 'filename' in LogRecord`. Loggningen använder
nu `document_name`; den misslyckade filen registreras och övriga resurser kan
fortsätta. Ett integrationstest reproducerade kraschen före rättningen och visar
sedan fortsatt bearbetning, sparad feladress och avslutning med varningar.
Resursgränsen är oförändrad. ARQ-hooken loggar inte längre `success: true` utan
belägg, eftersom ARQ inte tillhandahåller jobbresultatet i dess kontext.

## Kontrollerat källunderlag

- [Adminmeny](../../frontend/apps/web/src/routes/(app)/admin/AdminMenu.svelte),
  [sidans åtkomstkontroll](../../frontend/apps/web/src/routes/(app)/admin/+layout.ts)
  och [shadcn-konfiguration](../../frontend/apps/web/components.json).
- [Owner och behörigheter](../../backend/src/eneo/server/dependencies/predefined_roles.yml),
  [adminservice](../../backend/src/eneo/admin/admin_service.py) och
  [åtkomst till ytor](../../backend/src/eneo/actors/actors/space_actor.py).
- [CrawlRunRepository](../../backend/src/eneo/websites/domain/crawl_run_repo.py),
  [sparad crawlmodell](../../backend/src/eneo/database/tables/websites_table.py)
  och [befintlig detaljvy](../../frontend/apps/web/src/lib/features/knowledge/CrawlRunDetails.svelte).

- [Adminendpoint](../../backend/src/eneo/admin/admin_crawler_router.py) och
  [adminsidan](../../frontend/apps/web/src/routes/(app)/admin/crawler/+page.svelte).
