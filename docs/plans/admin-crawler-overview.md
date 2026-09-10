# Crawleröversikt i adminpanelen

Uppdaterad 10 september 2026. Översikten följs i Beads `crawl-f35` och
detaljer och åtgärder i `crawl-5x5`, gränssnittets förfining i `crawl-8ue`
och dagsstatistiken i `crawl-xve`,
alla i `crawler-review`. Sidan blir tillgänglig när backend, databas och frontend har
uppdaterats tillsammans.

Administratören kan se vad som körs i hela tenanten, vad som väntar och
vilka körningar som har fått fel. Sidan placeras på `/admin/crawler`, under
adminmenyns befintliga grupp för analys och loggar, med namnet **Crawler**.

## Sidans innehåll

Överst visas pågående körningar, kö och en genväg till senaste dygnets fel och
varningar. Därunder visas statistiken för **Idag** och **Igår**. De omfattar hela tenanten, oavsett
vilken del av tabellen som har laddats eller filtrerats.

| Sammanfattning | Betydelse |
| --- | --- |
| Pågående | Körningar i `running`, `finalizing` eller `stopping` just nu. |
| I kö | Körningar i `pending_dispatch` eller `queued` just nu. |
| Fel och varningar, senaste 24 timmarna | Avslutade körningar med `partial`, `failed` eller `interrupted`. Användaravbrott räknas inte som fel. |

Dagsstatistiken räknar körningar efter `finished_at` i webbläsarens IANA-tidszon,
som visas under siffrorna. Idag börjar vid lokal midnatt och slutar vid svarets
`as_of`. Igår omfattar hela föregående kalenderdag, även när den är 23 eller
25 timmar lång. Antalen avser körningar, inte unika webbplatser eller dokument.

| Dagsstatistik | Utfall |
| --- | --- |
| Slutförda utan fel | `succeeded`, `unchanged`, `empty`. Även en kontroll utan nytt innehåll är slutförd. |
| Med varningar | `partial`. Körningen avslutades men delar av resultatet misslyckades. |
| Misslyckade | `failed`, `interrupted`. |
| Manuellt avbrutna | `cancelled`, separat under de tre huvudtalen. |

Varje antal öppnar motsvarande dag och utfall i listan och rensar sökning och
sidindelning. Under statistiken finns två flikar: **Aktiva** som standard och
**Avslutade**. Aktiva innehåller både pågående och köade körningar. Avslutade
har periodvalen **Idag**, **Igår** och **Senaste dygnet**, med senast avslutad
först. Det går att filtrera på status och söka efter webbplatsens namn eller
adress. Genvägen för fel och varningar väljer uttryckligen **Senaste dygnet**.
Historiska fel ligger kvar där även om en senare körning har lyckats.

Tabellen har en rad per körning:

| Information | Visning |
| --- | --- |
| Webbplats | Namn och adress. Om namn saknas används adressen som etikett. Knappen öppnar körningsdetaljer. |
| Yta | Ytans namn så att samma webbplats i olika ytor går att skilja åt. |
| Status | Befintliga översatta statusetiketter. Köad, pågår, slutförs och stoppas går att skilja åt. |
| Resultat | Sidor och filer visas på varsin rad med lyckade och misslyckade antal i separata kolumner. Noll skiljs från saknad uppgift. |
| Tid | Väntetid för köade körningar; start och varaktighet för körningar som har startat. |
| Senast indexerad | Webbplatsens befintliga tidsstämpel, som bevaras vid ett senare fel. |

Aktiva körningar sorteras med äldst accepterad först, så att långa väntetider
syns. Skapandetid och verklig starttid hålls isär. Det finns inget känt totalantal
för alla crawls, så sidan visar räknare utan uppskattad procent eller sluttid.
En lång körning får inte automatiskt etiketten ”fastnad”.

Ett klick öppnar körningens detaljer med resultat, översatt felorsak och sidvis
hämtade feladresser. Äldre körningar kan sakna adressdetaljer. Fliken **Källa**
visar källans aktuella ägande yta, källägare, schema, senaste indexering och
senaste begärda körning. För manuella körningar visas den som begärde körningen när personen
kan identifieras från första försöket. Schemalagda körningar anges som
schemalagda; källägaren tillskrivs inte en manuell åtgärd.

**Lagrade dokument** räknar källans nuvarande aktiva dokument. Sidor och filer
räknas tillsammans eftersom de sparade dokumenten saknar en beständig typ som
skiljer dem åt. Körningens egna sid- och filräknare visas separat.
**Indexerad lagring** använder källans befintliga storleksredovisning, som
omfattar indexerat innehåll och vektorer. Den mäter inte databasens fysiska
utrymme eller säkerhetskopior. Båda värdena gäller källans aktuella innehåll,
även när en äldre körning är vald.

Fliken **Historik** visar även körningar äldre än ett dygn. **Samma adress**
visar andra källor i tenanten med exakt samma registrerade adress, deras ägande
yta, lagring och senaste indexering. Adresser normaliseras inte, och en träff
innebär inte att innehåll eller inställningar är identiska. En källa med tidigare
körningar kan öppnas direkt därifrån. En källa utan körning anges som sådan.
Översikten länkar inte till webbplatsens kunskapssida; adminbehörighet ger inte
i sig åtkomst till den ytan.

Administratören kan stoppa den valda körningen eller begära en ny körning.
**Försök igen** startar hela källan med dess aktuella inställningar. Redan sparat
innehåll hanteras av crawlerns befintliga regler. Båda åtgärderna bekräftas med
källans namn. Köad körning avbryts direkt; pågående arbete kan först gå till
**Stoppas**. Finns en annan aktiv körning visas en knapp för att öppna den.
Dialogens åtgärdsrad visar den valda körningens tid och status även när en
annan flik är öppen. Åtgärderna följer också en nyare status som hämtas med
körningens feladresser. Servern återanvänder en befintlig aktiv körning vid upprepad start, och ett stopp
av en äldre körning påverkar inte en senare körning.

## Feladresser från Kunskap

I webbplatslistan och indexeringshistoriken öppnar **Visa misslyckade sidor**
och **Visa misslyckade filer** rätt adresslista direkt. I körningsdetaljerna
går det att växla mellan **Alla**, **Sidor** och **Filer**, även genom att klicka
på ett positivt felantal. Typfiltret används på servern före sidindelningen,
så filer går att hitta även när de ligger efter många sidfel. Samma filter
finns i adminpanelens körningsdetaljer.

Varje adress visar en översatt felorsak. **Vad betyder felen och vad kan jag
göra?** förklarar vanliga orsaker och nästa steg. Äldre körningar utan sparade
adresser anges uttryckligen; de presenteras inte som felfria.

**Indexerat innehåll** visar en genväg till felen i den senaste avslutade
körningen, med körningens tid. Genvägen försvinner när en senare körning
avslutas utan fel. Tabellen visar fortfarande lagrat innehåll: en adress som
misslyckades nu kan ha en äldre indexerad version.

På webbplatsens kunskapssida kan den som har rätt att starta indexering välja
**Kör om hela webbplatsen** från felvyn. Det öppnar den befintliga
bekräftelsen och startar hela webbplatsen med aktuella inställningar. Endast
adresser som fortfarande kan upptäckas omfattas. Enskilda feladresser kan
inte köras om separat. Start erbjuds inte medan en körning redan är aktiv.

## Shadcn och uppdatering

Sidan använder projektets installerade **shadcn-svelte, Nova**, adminlayout och
semantiska färger. `Card` grupperar de två dagarna, `Tabs` vyerna,
`Table` körningarna, `Badge` status och `Input`/`Select` filtreringen. Den använder befintlig `Dialog` för körningsdetaljer. Ingen ny komponentfamilj behövs.

Sidan uppdateras var tionde sekund medan sidan är synlig, med högst en pågående
uppdatering. Filter och befintliga rader behålls vid uppdatering av samma lista. Vid
filterbyte ligger statistiken kvar medan den nya listan laddas. När ett nytt
kalenderdygn börjar återgår dagens och gårdagens listor till första sidan. Sidan visar
”Senast hämtat” och en manuell uppdateringsknapp. Vid fel behålls senaste
resultatet med ett tydligt felbesked och möjlighet att försöka igen.
Felbeskedet och knappen ligger kvar medan försöket pågår; knappen visar att
den arbetar och hindrar dubbla klick. Aktiva sök- och statusfilter kan rensas
med en gemensam knapp. Noll
aktiva körningar ska vara ett begripligt normaltillstånd. Skeleton används vid
första laddningen. Tangentbord, fokus, svenska/engelska och smala skärmar ska
fungera med de befintliga komponenterna.

Detaljer hämtas när dialogen öppnas, vid manuell uppdatering och efter en
åtgärd. Historik och samma adress hämtas först när respektive flik öppnas, tio
rader åt gången. Dessa frågor ingår inte i översiktens uppdatering var tionde sekund.
Dialogen behåller bara aktuell resultatsida. Sena svar för en tidigare vald
källa kan inte ersätta den nya källans detaljer. Vid fel finns möjlighet att
försöka igen. Varje flik har en uppdateringsknapp för sitt innehåll. Historik
och samma adress uppdateras på den valda resultatsidan. Uppdatering av **Källa**
hämtar även den valda körningens status och feladresser. En uppdatering av
körningsdetaljer ersätter adresslistan från första sidan när hämtningen lyckas;
befintliga adresser ligger kvar medan hämtningen pågår eller om den misslyckas.

Massåtgärder, ändringar av källinställningar, grafer, kostnadsberäkningar och
aviseringar ingår inte.

## Behörighet och data

Använd samma `admin`-behörighet som resten av adminpanelen; den ingår i den
fördefinierade rollen Owner. Skydda både sidan och backendmetoderna. Tenantens
identitet hämtas från den autentiserade användaren, aldrig från ett valbart
tenant-id i klienten. Befintliga krav på API-nycklars adminomfattning gäller även
här. Inga nya behörigheter eller rollnamnsjämförelser behövs.

Owner har inte automatiskt läsrätt till alla privata ytor. Tenantöversikten
har därför uttrycklig adminåtkomst till körningsmetadata, feladresser och
start/stopp även för dessa ytor. Varje vald körning och källa slås upp inom den
autentiserade tenanten före åtgärden. Det ger inte rätt att läsa indexerat
innehåll, ändra källinställningar eller radera källor. Behörigheten till den
vanliga kunskapssidan fortsätter att prövas som tidigare.

Start kräver en riktig användaridentitet; en fristående service-API-nyckel kan
inte skapa en körning, men en service-API-nyckel med tenantens adminomfattning
kan läsa metadata och stoppa en körning.

En ny adminbegärd körning använder den begärande administratörens konto. Nya
innehållsversioner får den användaren som upphov och räknas mot användarens
lagringskvot. Även en adminbegärd körning kan därför nå användarens kvotgräns.
Källans ägare ändras inte; befintliga innehållsversioner behåller sin tidigare
användare. Om en redan aktiv körning återanvänds behåller den sin ursprungliga
körningsidentitet. Bekräftelsen för en ny körning förklarar kvotkonsekvensen.

Adminbegäran om start och stopp skrivs som separata
händelsetyper i befintlig revisionslogg, med aktör, källa, körnings-id och
returnerad status. När loggning är aktiverad sparas åtgärd och revisionspost i
samma transaktion. Om loggningen misslyckas rullas åtgärden tillbaka. Befintlig
avstängning av loggning eller dess integrationskategori respekteras.

API-ytan ligger under `/api/v1/admin/crawler/`:

| Metod och sökväg | Innehåll eller åtgärd |
| --- | --- |
| `GET /` | Sammanfattning och en begränsad sida med körningar. |
| `GET /runs/{id}/` | Vald körning och källans aktuella metadata. |
| `GET /runs/{id}/failures/` | Körningens sparade feladresser. |
| `GET /websites/{id}/runs/` | Källans körningshistorik. |
| `GET /websites/{id}/matches/` | Andra källor med exakt samma adress. |
| `POST /websites/{id}/run/` | Begär en ny körning eller returnera befintlig aktiv körning. |
| `POST /runs/{id}/cancel/` | Begär stopp av den valda körningen. |

Befintliga svarstyper för körningar och fel används inne i projektionen;
klienttyper genereras från OpenAPI. Resultat och feladresser har en gemensam
UI-komponent som används med rätt hämtfunktion för respektive behörighetskontext.
Adminsidans ägarskapsinformation och åtgärder ligger i dess egen dialog.
Läsningar återanvänder `CrawlRunRepository` och `WebsiteSparseRepository`;
åtgärder återanvänder `CrawlService` utan ett nytt status- eller kölager.

Läsningen ägs av befintlig `CrawlRunRepository` och använder adminpanelens
behörighetskontroll. Läs enbart nödvändiga fält från körningar, aktuellt försök,
webbplatser och ytor. Hämta inte alla ytors innehåll eller alla jobb till
webbläsaren. Begränsa varje sida till högst 100 rader och använd stabil cursor
med tidsstämpel och id. Dygnsvyn avgränsas av avslutningstid; sammanfattningens
tidpunkt returneras så att siffrorna går att tolka. `period` väljer
`today`, `yesterday` eller `last_24_hours`; `time_zone` valideras som en
IANA-tidszon. Utelämnade parametrar behåller API:ts tidigare rullande dygnsvy
och använder UTC. `calendar` innehåller tidszon, datum och dagarnas fyra
antal. Samma tidsgränser och utfallsgrupper används i statistiken och listan.
Sammanfattningen läser aktiva körningar och det tidsintervall som täcker både
igår och de senaste 24 timmarna, oberoende av hur mycket äldre historik finns.
Dagarnas räknare ingår i befintlig aggregatfråga; ingen extra fråga per dag,
ny tabell eller separat uppdateringsloop behövs.

`CrawlRuns`, `CrawlAttempts`, `CrawlRunFailures` och `Websites.last_indexed_at`
innehåller underlaget. Jobblistan är användarspecifik och den befintliga
hälsosammanfattningen gäller hela installationen; ingen av dem kan användas
direkt som tenantöversikt. Nya statuslager, köer, summeringstabeller och ändringar
av crawlerns körning behövs inte. Historikfrågorna använder ett partiellt index på tenant, avslutningstid och id
för avslutade körningar. Aktiva körningar har ett separat partiellt index på
tenant, skapandetid och id, vilket låter databasen läsa tabellens sorteringsordning
direkt. Inget av dessa index duplicerar webbplatsindexets sorteringsordning.

## Verifiering och drift

Dagsstatistiken verifierades med 20 admintester mot PostgreSQL och 20 tester i
riktig webbläsare. De täcker avslutsdatum, lokala dygnsgränser, sommartidsbyte,
utfallsfilter, tenantgränser, ogiltiga parametrar och återgång till första
historiesidan vid nytt dygn. Strikta typkontroller och 42 SDK-tester passerar.
Skalningsprovet med 100 000 äldre körningar och upp till 10 000 aktiva behåller
två databasfrågor för översikten; aggregatet läser inte igenom äldre historik.
Det är ett lokalt mätprov, inte ett kapacitetslöfte för produktion.

Den första versionen verifierades med 80 PostgreSQL-integrationstester för adminåtkomst,
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

Migrationerna `202609091600` och `202609091830` skapar indexen för avslutad
respektive aktiv historik med `CREATE INDEX CONCURRENTLY`.
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

## Många aktiva körningar

Webbplatsnamn är valfria i datamodellen. API-projektionen och den genererade
klienttypen bevarar därför `null`; användargränssnittet använder adressen som
etikett. Regressionstestet omfattar en namnlös webbplats under pågående körning,
sökning på adress och efter avslutning. Webbläsartestet öppnar dess feldetaljer
och kontrollerar att tangentbordsfokus återgår till samma knapp. Korrigeringen
verifieras med åtta API-tester och sju webbläsartester. Nio migrationstester
kontrollerar upp- och nedgradering, inklusive att spärrad återställning lämnar
schemat och sparade data intakta.

Prestandaprovet använder den riktiga HTTP-endpointen, inklusive autentisering
och serialisering, mot PostgreSQL 16 i en disponibel testcontainer. Underlaget
är 100 000 äldre avslutade körningar plus 100, 1 000 eller 10 000 aktiva körningar,
hälften köade och hälften pågående. En fjärdedel av webbplatserna saknar namn.
Efter uppvärmning mäts sju hämtningar per fall; dataskapande, frågeplansanalys och
allokeringsmätning ligger utanför tidsmätningen.

Miljö: CPython 3.11.16 med GIL, optimerad releasebyggnad med LTO, Linux aarch64,
SQLAlchemy 2.0.51, asyncpg 0.27.0, FastAPI 0.138.2 och Pydantic 2.13.4.
Testprocessen har fyra CPU:er och 6 GiB minnesgräns. Databascachen är varm.

| Aktiva körningar | Första sidan före indexet, median (min–max) | Med indexet, median (min–max) |
| --- | --- | --- |
| 100 | 14,01 ms (12,31–14,58) | 11,18 ms (10,40–12,27) |
| 1 000 | 13,90 ms (12,76–14,46) | 10,62 ms (10,50–11,84) |
| 10 000 | 28,55 ms (27,63–36,44) | 12,88 ms (12,49–13,33) |

Frågeplanen för 10 000 aktiva körningar visar den avgörande skillnaden: tidigare
lästes och sorterades hela den aktiva mängden. Indexet läser 51 rader i rätt
ordning för en sida med 50 resultat och en fortsättningsmarkör. Den isolerade
sidfrågan tog 11,98 ms före och 0,17 ms efter. Sammanfattningsfrågan läser fortfarande
alla relevanta körningar och tog omkring 1,8 ms i båda fallen.

Antalet crawlerfrågor är två på första sidan och tre med cursor, oberoende av
antalet körningar. API:t tillåter högst 100 resultat; gränssnittet begär 50 och
behåller bara aktuell sida. Svaren för 50 rader var cirka 35 kB och toppvärdet för
spårade Python-allokeringar cirka 0,50 MiB vid samtliga storlekar. Processens
CPU-tid för en sida var ungefär 10–12 ms. Hela testprocessens RSS-topp, inklusive
uppstart och dataskapande, var cirka 452–465 MiB; det är inte endpointens minnesåtgång.
Tio samtidiga HTTP-hämtningar slutfördes utan fel. Provet är ingen mätning av
produktionens p95/p99 eller av genomströmningen när crawlerarbetare också belastar
systemet.

Med `A` aktiva körningar, `R` avslutade senaste dygnet och `P` resultat per sida
är sammanfattningen fortfarande linjär i `A + R`. Den ofiltrerade sidans sökning
i indexet undviker den tidigare sorteringen av `A` rader. API-materialisering
och rendering är linjära i det begränsade `P`. Fritextsökning kan behöva läsa
webbplatsernas namn och adresser; den mätta sökningen vid 10 000 aktiva körningar
tog cirka 20 ms inklusive hela HTTP-anropet. En ytterligare körning efter den färdiga migrationen gav 14,51 ms för
första sidans median vid 10 000 aktiva körningar. Indexet förbättrar ordnad läsning
och kostar ett extra indexunderhåll när en körning skapas eller avslutas.

Det återanvändbara provet finns i
[test_admin_crawler_benchmark.py](../../backend/tests/integration/test_admin_crawler_benchmark.py)
och körs separat från vanliga tester:

```bash
cd backend
ENEO_RUN_CRAWLER_OVERVIEW_BENCHMARK=1 uv run pytest -s -m integration \
  tests/integration/test_admin_crawler_benchmark.py
```

## Skalning för detaljer och åtgärder

Utökningen ändrar inte översiktens återkommande SQL-frågor. Ett separat prov
mätte de nya läsningarna med 100 001 källor, 100 000 aktiva dokument och
100 000 äldre körningar för den valda källan. Elva andra källor hade samma
adress. Miljö, uppvärmning och sju HTTP-mätningar per fall följde provet ovan.

| Läsning | Median (min–max) | Crawlerfrågor per hämtning | Svarsstorlek |
| --- | --- | --- | --- |
| Detaljer | 21,75 ms (21,32–22,23) | 4 | 1 510 byte |
| Historik, tio rader | 15,32 ms (14,89–15,87) | 3 | 4 860 byte |
| Samma adress, tio rader | 17,58 ms (16,10–19,78) | 2 | 2 934 byte |
| Samma adress, inga träffar | 16,03 ms (15,21–17,15) | 2 | 31 byte |

Autentisering tillkommer med fem läsfrågor i den testade miljön. En registrerad
manuell initiator kräver ytterligare en begränsad användarfråga; provet använde
äldre körningar utan den uppgiften. Spårade Python-allokeringar låg runt
0,49–0,54 MiB per hämtning. Inga dokumenttexter eller vektorer lästes in.

Historiksidan hämtar elva rader via befintligt index och returnerar tio.
Totalantalet historiska körningar och aktiva dokument måste fortfarande räknas.
Adressmatchningen läste 100 001 källor i detta prov och tog cirka 6,4–6,7 ms i
SQL. Kostnaden växer med antalet källor; detta är ingen konstanttidsfråga.
Dokumenträkningen tog cirka 11,3 ms när samtliga 100 000 dokument tillhörde den
valda källan. Begränsade svar och hämtning vid behov håller detta arbete utanför
översiktens återkommande uppdatering. Provet motiverar inget ytterligare index i
den här ändringen och säger inget om produktionens p95/p99 under samtidig
crawling. Utökningen kräver ingen ny migration.

Detaljer och åtgärder verifierades med 102 PostgreSQL-integrationstester,
176 berörda enhetstester, 46 frontendtester och 42 SDK-tester. Kontrollerna
omfattar bland annat andra tenanter, privata källor, namnlösa källor,
användarattribution efter att kompatibilitetsjobbet tagits bort, upprepad start,
stopp av en äldre körning, rollback vid revisionsfel, paginering och återhämtning
efter misslyckade hämtningar eller åtgärder. Genererat API-kontrakt, strikta
typer, lint, språknycklar och dialogens breda, mellanbreda och smala layouter i
ljust och mörkt tema kontrollerades också.

## Kontrollerat källunderlag

- [Adminmeny](../../frontend/apps/web/src/routes/(app)/admin/AdminMenu.svelte),
  [sidans åtkomstkontroll](../../frontend/apps/web/src/routes/(app)/admin/+layout.ts)
  och [shadcn-konfiguration](../../frontend/apps/web/components.json).
- [Owner och behörigheter](../../backend/src/eneo/server/dependencies/predefined_roles.yml),
  [adminservice](../../backend/src/eneo/admin/admin_service.py) och
  [åtkomst till ytor](../../backend/src/eneo/actors/actors/space_actor.py).
- [CrawlRunRepository](../../backend/src/eneo/websites/domain/crawl_run_repo.py),
  [sparad crawlmodell](../../backend/src/eneo/database/tables/websites_table.py)
  och [gemensamt detaljinnehåll](../../frontend/apps/web/src/lib/features/knowledge/CrawlRunDetailsContent.svelte).

- [Adminendpoint](../../backend/src/eneo/admin/admin_crawler_router.py) och
  [adminsidan](../../frontend/apps/web/src/routes/(app)/admin/crawler/+page.svelte) och
  [admindialogen](../../frontend/apps/web/src/routes/(app)/admin/crawler/AdminCrawlDetails.svelte).
