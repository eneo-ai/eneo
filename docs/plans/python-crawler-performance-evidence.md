# Prestandaunderlag för Python-crawlern

## Kort slutsats

Crawlern har en stabil grund: oförändrade sidor bäddas inte in på nytt, databassessioner hålls inte öppna under provideranrop och upprepade körningar har inte visat någon minnesläcka. Den här leveransen behåller vektorer som `float32`, packar embedding-indata efter modellens befintliga kapabilitet och fyller lediga HTTP-platser löpande.

Genomförd omfattning:

1. Behåll embedding-vektorer som `float32` och mät faktisk minnesstorlek.
2. Packa texter över den befintliga, begränsade sidbatchen och låt modellens `max_batch_size` styra varje provideranrop.
3. Ersätt fasta HTTP-batcher med fyra löpande platser per crawl, utan att höja samtidigheten.

Den fasta pausen på 100 ms behålls. Dess produktbetydelse och eventuell batchlokal återanvändning av identiska embedding-indata är separata, senare beslut.

Inget av detta ska ändra chunkstorlek, chunktext, sidurval, vektordimension, robotsregler, återförsök eller publiceringsregler.

## Omfattning och mätmiljö

- Gren: `feature/python-crawler`
- Jämförelsebas före optimering: `d87315dff`
- Kandidat: prestandaändringarna och detta underlag i samma efterföljande commit
- Python: CPython 3.11.16 på Linux aarch64
- Crawl-jobb per worker: 15
- HTTP-platser per crawl: 4
- Globala HTTP-platser per workerprocess: 20
- Embedding-samtidighet: 3
- Sidbatch: högst 100 sidor och 10 MiB råtext
- Standardgräns för ett HTTP-anrop: 90 sekunder
- Dedikerad crawler-worker i vila: cirka 431 MiB RSS och 7 trådar

Den här rapporten skiljer på uppmätta resultat och föreslagna förändringar. Providerresultaten används för att verifiera den generella mekanismen mot respektive modells egna kapabiliteter, inte för att rangordna embeddingmodeller. En batchgräns som fungerar för en provider-/modellkombination får inte användas som generellt gränsvärde för andra providers eller driftsätt.

## Verifierad utgångspunkt

### Oförändrade sidor

En omkörning av en crawl med 354 publicerade sidor tog 36,12–36,78 sekunder och gjorde noll embedding-anrop och noll innehållsskrivningar. Ursprungswebbplatsen skickade varken ETag eller Last-Modified, så crawlern måste fortfarande hämta och tolka sidorna innan SHA-256-jämförelsen kan visa att innehållet är oförändrat.

### Minnesstabilitet

En upprepad verklig crawl ökade processens RSS från 439,8 till 450,3 MiB som mest. Antalet trådar låg kvar på 7 och öppna filbeskrivare gick från 12 till 16 och tillbaka till 12. De genomförda körningarna visar ingen fortlöpande tillväxt, men de ersätter inte ett långvarigt produktionstest.

Efter request-packningen kördes samma 355-sidorskälla fyra gånger till i samma
workerprocess. Samtliga sidor var oförändrade. Körningarnas RSS vid start och
slut var 422,27 → 411,55 MiB, 411,55 → 409,62 MiB, 409,62 → 417,66 MiB och
417,66 → 418,64 MiB. Högsta samplade värde var 426,33 MiB. Slutvärdet efter
fyra körningar låg 3,63 MiB under den första startpunkten. Serien visar ingen
monoton minnesökning. Den utesluter inte en långsamt växande läcka under längre
produktionstid.

### Verkliga kalla crawls

| Crawl | Sidor | Misslyckade sidor | Chunks | Embedding-anrop | Beräknade indatatokens | Tid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sundsvall, kommun och politik | 354 | 1 | 4 189 | 400 | 621 475 | 131,70 s |
| Sundsvall, utbildning och förskola | 507 | 6 | 6 200 | 546 | 978 801 | 215,44 s |

Den största sidan i den första korpusen gav 261 chunks. Med dagens standardbatch på 32 innebär det upp till nio provideranrop för en enda sida under samma 15-sekunders timeout.

## Beslutade optimeringskandidater

### 1. Behåll vektorer som `float32`

Före ändringen behöll `PreparedPage` varje vektor som en Python-lista med Python-flyttal, samtidigt som minnesvakten räknade fyra byte per dimension. Den beräkningen motsvarade den slutliga `float32`-vektorn i PostgreSQL, inte Python-objekten som faktiskt låg i minnet.

En kontrollerad jämförelse med 1 200 vektorer och 1 536 dimensioner gav:

| Representation | Mätt minne |
| --- | ---: |
| Python `list[float]` | 56,32 MiB |
| NumPy `float32` | 7,17 MiB |

Skillnaden var 7,85 gånger. Verkliga sidbatcher innehöll som mest ungefär 1 226–1 335 chunks, vilket motsvarar cirka 57,5–62,6 MiB som Python-listor och 7,2–7,8 MiB som `float32`.

PostgreSQL lagrar redan vektorerna i enkel precision. Den exakta bulk-insert-form som crawlern använder accepterade en `float32`-array och läste tillbaka samma `float32`-värden bit för bit i en testtransaktion som sedan återställdes.

Genomförd förändring:

- behåll varje förberedd vektor som en `float32`-array;
- använd `array.nbytes` för minnesgränsen;
- när gränsen nås, publicera den redan förberedda prefixdelen och fortsätt med resten;
- hoppa aldrig över en sida eller chunk för att hålla minnet under gränsen.

`ChunkEmbeddingList` skriver fortfarande vektorer som `float64` till en temporär
fil. Den komponenten delas med filuppladdning och ändras inte i den här
leveransen. Crawlern konverterar först när vektorerna behålls inför publicering,
vilket är minneskostnaden som mäts här. En separat spooländring kräver egen
mätning och kontraktsverifiering för både crawl- och uppladdningsvägen.

#### Isolerad worker-RSS före och efter

Fem alternerande färska Linuxprocesser importerade hela crawler-workerns
runtimegraf och behöll sedan 1 780 vektorer med 1 024 dimensioner, samma största
vektorbuffer som den verkliga E5-körningen. Båda representationerna gav samma
checksumma, 805,074223.

| Representation | Bas-RSS | RSS med vektorer | Vektordelta | Processens topp-RSS |
| --- | ---: | ---: | ---: | ---: |
| Python `list[float]` | 370,45 MiB | 441,34 MiB | 70,902 MiB | 441,06 MiB |
| NumPy `float32` | 370,43 MiB | 377,96 MiB | 7,531 MiB | 377,64 MiB |

`float32` minskade den behållna vektordeltan med 89,4 procent, cirka 9,4 gånger,
och processens uppmätta topp med cirka 63,4 MiB eller 14,4 procent. Mätningen
isolerar representationsskillnaden från nätverk, provider och allocatorcache.

### 2. Packa embedding-indata efter modellens kapabiliteter

Crawlern skapar i dag en adapter per sida och låter varje sida börja om på en ny providerbatch. Små sidor fyller därför sällan en batch. Packningen bör ske över den befintliga sidbatchen, som redan begränsas av antal sidor och råtextens storlek. Resultaten mappas sedan tillbaka till varje ursprunglig sida och chunk i oförändrad ordning.

Den befintliga modellinställningen `max_batch_size` är rätt ägare för antal texter per provideranrop. Koden ska inte känna till att en viss modell råkar tåla 32, 128 eller 256 texter. Om värdet saknas behålls dagens standard 32.

Mätningen med 128 verkliga chunks från den lokalt konfigurerade OpenAI-modellen gav:

| Strategi | Provideranrop | Median |
| --- | ---: | ---: |
| Dagens sidvisa, sekventiella anrop | 14 | 4,471 s |
| Packade grupper om 32, sekventiellt | 4 | 2,045 s |
| En modellkonfigurerad grupp om 128 | 1 | 1,317 s |
| Packade grupper om 32, tre parallellt | 4 | 1,400 s |

Den sista jämförelsen visar att extra parallell providerlogik inte behövs för den testade modellen när modellkonfigurationen medger 128. Det är inte evidens för att alla providers ska använda 128. Varje provider/modell ska mätas innan dess `max_batch_size` höjs.

#### Före/efter med samma GDM/E5-rutt och samma verkliga chunks

Efter implementationen kördes 512 oförändrade chunks från 52 Sundsvall-sidor
tre gånger genom samma provider, modell, prefix och standardbatch 32. Ordningen
alternerades mellan den tidigare sidvisa strategin och den nya packningen för
att minska ordningseffekter från TLS- och processuppvärmning.

| Strategi | Verkliga provideranrop | Median väggtid | Median CPU |
| --- | ---: | ---: | ---: |
| Sidvis, varje sida börjar om | 59 | 5,955 s | 1,574 s |
| Packad över samma begränsade sidbuffert | 16 | 2,961 s | 0,912 s |

Packningen tog bort 72,88 procent av provideranropen, halverade väggtiden
(2,01 gånger snabbare) och minskade processens CPU-tid med cirka 42 procent i
den här isolerade jämförelsen. Alla sex mätningar returnerade 512 vektorer i
ursprunglig chunkordning och samtliga vektorer hade 1 024 dimensioner.

Providerresponsen var inte bitidentisk mellan batchformerna. Det är en egenskap
hos den aktuella modellserverns batchberäkning, inte `float32`-konverteringen:
över tre par var minsta cosinuslikhet 0,999991, medianen cirka 0,9999994 och
största absoluta komponentavvikelse 0,000461. Fem fasta svenska sökfrågor gav
samma toppresultat och 10 av 10 samma träffar i topp 10 för båda
batchformerna; största skillnaden i likhetspoäng var 0,000271. Detta är starkt
stöd för bevarad retrieval i den uppmätta korpusen, men inte ett löfte om
bitidentiska providerresultat.

RSS-värdena från denna process används inte som före/efter-bevis eftersom
strategierna delar allocator-, TLS- och modellklientcache i samma process.
Minnesbeslutet grundas i stället på de separata representationsmätningarna och
ska slutverifieras med en kall helcrawl i workerprocessen.

#### Kall och varm helcrawl i workerprocessen

En ny källa för `https://sundsvall.se/kommun/omsorg-och-hjalp` kördes genom den
omstartade crawler-workern med GDM/E5-rutten och filnedladdning avstängd.
Körningen nådde terminalt läge efter 43,11 sekunder med 355 hämtade sidor,
354 publicerade sidor och en säker redirectavvisning. Fyra begränsade
sidbuffertar planerade sammanlagt 3 409 chunks och skickade 109 provideranrop.

De 354 publicerade sidorna innehöll 3 404 chunks. Om varje sida hade börjat om
på en ny batch om 32 hade just dessa chunks krävt 368 provideranrop. Den
packade körningen gjorde därmed minst 70,4 procent färre anrop, trots att dess
109 anrop även omfattade den sida som senare inte publicerades.

En omedelbar omkörning nådde samma terminalresultat efter 36,71 sekunder.
Samtliga 355 hämtade sidor hashmatchade tidigare innehåll, och antalet
provideranrop låg kvar på 109. Omkörningen gjorde alltså noll nya
embedding-anrop och förbrukade inga nya embeddingtokens. Tre ytterligare
omkörningar gav samma resultat och tog 37,11–39,08 sekunder räknat från skapad
till avslutad körning.

#### Ingen latensstyrd batchregulator

Svarstiden ska inte styra batchstorleken. Den blandar providerbelastning,
nätverkstid, textlängd, köväntan och eventuella återförsök och säger inget
säkert om hur stor request providern accepterar. En snabb respons kan vara ett
avvisat anrop och en långsam respons kan vara ett fullt giltigt anrop.

Den generella lösningen använder därför modellruttens verifierade
`max_batch_size` som hård gräns och behåller 32 när värdet saknas. Löpande
semaforplatser gör redan genomströmningen responsstyrd utan en regulator: en
plats släpps efter varje provideranrop, så andra crawls kan fortsätta medan en
provider är långsam. En timeout är tvetydig och skickas inte om automatiskt,
eftersom providern kan ha hunnit slutföra och debitera anropet.

Packningen behöver ingen särskild runtime-fallback till sidvis behandling.
Requeststorleken och anropsordningen mot providern är desamma som tidigare;
skillnaden är att ledigt utrymme fylls med chunks från nästa sida. Om en
providerbatch misslyckas publiceras endast helt färdiga sidor före felgränsen,
och resten får ett typat embeddingfel.

Första genomförandet bör vara sekventiellt:

- en kortlivad adapter per förberedd sidbatch;
- `max_batch_size` från modellposten;
- den globala embedding-semaforen för varje faktiskt provideranrop;
- en timeout för varje faktiskt provideranrop, inte för en hel sida eller sidbatch;
- ett typat delfel som anger hur många chunks i den ordnade prefixdelen som blev klara;
- sidor som är helt täckta av prefixdelen får publiceras, medan första berörda sida och resten får ett uttryckligt embedding-fel;
- providerparametrar och dekrypterade uppgifter beräknas en gång per kortlivad adapter, inte en gång per underbatch.

Detta är provideroberoende. Det kräver ingen ny batching-tjänst, ingen modellnamnstabell och ingen extra samtidighetsinställning.

### 3. Hantera 512-tokenmodeller utan specialfall för E5

`max_input` och `max_batch_size` beskriver olika gränser:

- `max_input` är högsta tillåtna antal tokens för en text;
- `max_batch_size` är högsta antal texter i ett provideranrop.

Crawlern delar för närvarande innehåll i chunks om 200 tokens. Det ligger under en korrekt konfigurerad 512-tokenmodell även efter det korta E5-prefixet `passage:`. Vi ska inte öka chunkstorleken till 512 som en prestandaändring. Det skulle ändra sökresultat, kontextfördelning och tokenkostnad och kräver en separat retrieval-utvärdering.

En 512-tokenmodell kan däremot dra nytta av samma generella request-packning som andra modeller. Hur många 200-tokentexter som kan skickas tillsammans styrs av `max_batch_size`, inte av 512-gränsen. Om en provider även har en gräns för sammanlagda tokens eller bytes per request behöver den gränsen modelleras separat först när den är verifierad; den ska inte härledas genom att gissa från modellnamnet.

Den första E5-konfigurationen visade två metadatafel:

- API-modellerna beskriver `max_input` som tokens, medan `EmbeddingModelSpec` beskriver samma fält som tecken och query-vägen beskär en Python-sträng efter antal tecken.
- Den nya providerimporterade modellen fick först `family=openai` och saknade inputgräns och dimensioner. Den lokala, äldre katalograden för samma modell anger samtidigt 8 191, medan senare migrationsunderlag anger 512.

Att spara dimensioner 1 024 på den nya modellen exponerade ytterligare en sammanblandning. Adaptern skickar alla lagrade dimensioner som requestparametern `dimensions`. LiteLLM avvisade därför anropet innan det nådde GDM, eftersom en OpenAI-kompatibel E5-endpoint inte stöder en sådan dimensionsoverride. Med dimensioner tomt i modellposten returnerade providern korrekt 1 024 värden per vektor. Modellens utmatningsdimension och stöd för dimensionsoverride behöver därför vara två olika kapabiliteter.

Detta motiverar en liten korrekthetskontroll av modellmetadata, exakt tokenräkning efter providerprefix och separata kapabiliteter för lagrad dimension respektive requestoverride. Det motiverar inte hårdkodade E5-värden i crawlern.

### GDM/E5: kapabilitetsstyrd batchmätning

Samma 256 verkliga crawlchunks kördes två gånger per batchstorlek mot den
konfigurerade GDM/E5-rutten. Varje körning returnerade en vektor per chunk med
1 024 dimensioner. Mätningen avgör endast en lämplig `max_batch_size` för denna
modellrutt.

| Batchstorlek | Median | Förbättring från batch 32 |
| ---: | ---: | ---: |
| 32 | 1,612 s | referens |
| 64 | 1,357 s | 1,19 gånger |
| 128 | 1,280 s | 1,26 gånger |
| 256 | 1,177 s | 1,37 gånger |

En separat testserie skickade texter som var 508 tokens långa efter
`passage:`-prefixet:

| Batchstorlek | Tid | Texter per sekund | Returnerade vektorer |
| ---: | ---: | ---: | ---: |
| 32 | 0,389 s | 82 | 32 |
| 64 | 0,629 s | 102 | 64 |
| 128 | 1,057 s | 121 | 128 |
| 256 | 2,078 s | 123 | 256 |

Alla fyra storlekar gav 1 024 dimensioner utan providerfel. Ökningen från 128
till 256 gav cirka två procent högre genomströmning nära tokentaket men
dubblerade requestens payload. Resultatet beskriver endast den testade
providerkonfigurationen. Det ska inte användas för att automatiskt välja en
gräns utifrån svarstid; driftansvarig behöver ange en verifierad kapabilitet i
modellruttens metadata.

En separat process per E5-variant gav renare temporära resursvärden:

| Modell | Batch | Tid | CPU | RSS-ökning under anropet |
| --- | ---: | ---: | ---: | ---: |
| GDM/E5 | 32 | 1,798 s | 0,573 s | 9,7 MiB |
| GDM/E5 | 128 | 1,343 s | 0,520 s | 13,4 MiB |

För GDM/E5 kostade batch 128 ungefär 3,7 MiB mer temporärt RSS än batch 32 i den isolerade processen och minskade tiden med cirka 25 procent. Den globala embedding-semaforen begränsar fortfarande samtidiga provideranrop till tre. Den planerade `float32`-ändringen gäller de vektorer som behålls efter provideranropet och är fortfarande motiverad.

### Verklig 354-sidorscrawl med E5

Den fulla Sundsvall-körningen gav 354 publicerade sidor, en säker
redirectavvisning och 4 190 lagrade chunks på 62,30 sekunder. Samtliga chunks
hade 1 024 dimensioner och ingen embedding saknades. E5-tokenisering efter det
obligatoriska `passage:`-prefixet gav totalt 486 692 tokens; den största chunken
var 276 tokens och ingen överskred modellens gräns på 512.

Dagens sidvisa batching började om för varje sida och krävde 400 provideranrop
med standardbatch 32. Packning över de fyra befintliga, begränsade
sidbuffertarna hade krävt:

| Modellens `max_batch_size` | Sidvisa anrop i dag | Packade anrop | Packade anrop efter exakt batchlokal återanvändning |
| ---: | ---: | ---: | ---: |
| 32 | 400 | 132 | 126 |
| 64 | 400 | 67 | 64 |
| 128 | 400 | 34 | 33 |
| 256 | 400 | 18 | 18 |

Detta visar hur mycket transportarbete den generella packningen kan ta bort;
det är inte i sig en före/efter-mätning av hela crawltiden. De uppmätta
batchstorlekarna är konfigurationsunderlag för just den här modellrutten och får
inte hårdkodas eller väljas automatiskt från en enstaka svarstid.

Exakt återanvändning inom respektive sidbuffert skulle ha sparat 19 757 tokens,
4,06 procent, utan att ändra någon chunk. Den största sidbufferten innehöll
1 780 vektorer. Dagens minnesvakt räknade dem som 6,95 MiB, medan de faktiska
Python-listorna motsvarar cirka 55,72 MiB. `float32`-arrayer motsvarar cirka
7,14 MiB. Den verkliga körningen bekräftar därför att minnesvakten i dag
underskattar den behållna vektorgrafen med ungefär 7,8 gånger.

### 4. Fyll HTTP-platser löpande

Före ändringen tog motorn upp till fyra URL:er, väntade på att samtliga skulle bli klara och startade sedan nästa grupp. En långsam sida lämnade därför färdiga platser tomma. Motorn fyller nu nästa URL när en plats blir ledig, utan att höja någon samtidighetsgräns.

Fem färska körningar mot samma lokala latensprofil använde 80 sidor, varav sju
avsiktligt långsamma. Medianerna nedan jämför exakt commit `d87315dff` med den
nya motorn i separata processer. Samtliga körningar gav samma 80 sidor och högst
fyra samtidiga anrop.

| Pacing | Fasta fyragrupper | Löpande platser | Förbättring |
| --- | ---: | ---: | ---: |
| Ingen fast paus | 1,7438 s | 0,8427 s | 2,07 gånger |
| 100 ms före påfyllning | 3,8052 s | 2,8232 s | 1,35 gånger |

Median CPU-tid var 0,0737 → 0,1479 sekunder utan paus och 0,0833 → 0,0994
sekunder med 100 ms paus. Den lokala mätningen räknar både testserver och klient i
samma process, men visar ändå den väntade kostnaden av fler event-loop-väckningar.
Vinsten är lägre väggtid på nätverksbunden hämtning, inte lägre CPU i själva
HTTP-schemaläggaren. Den absoluta ökningen utan paus var cirka 0,9 ms per sida.

Långsamma webbplatser ska isoleras så här:

- en crawl får fortfarande högst fyra HTTP-platser;
- workerprocessen får fortfarande högst 20 samtidiga HTTP-anrop;
- en långsam URL upptar en plats, inte en hel fyragrupp;
- robots `Crawl-delay` fortsätter att tvinga seriell hämtning för den aktuella webbplatsen;
- återförsök, `Retry-After`, stopp och den totala crawlgränsen behålls.

En ensam långsam webbplats kan därmed inte ta mer än fyra av tjugo platser och ett av femton crawl-jobb. Om fem långsamma crawls samtidigt fyller alla tjugo HTTP-platser får en liten crawl vänta tills ett pågående anrop avslutas. Med standardgränsen 90 sekunder kan detta bli märkbart om alla anrop verkligen hänger. Att garantera reserverad kapacitet för varje nytt jobb kräver en separat rättvis kö och är inte motiverat utan ett reproducerat svältfall.

Ett flerjobbtest fyller samtliga 20 globala platser med fem långsamma crawls och
startar därefter en liten snabb crawl. När exakt en plats frigörs får den väntande
lilla crawlen platsen före en långsam crawl fyller på igen. Testet passerade fem
upprepningar. Separata beteendetester täcker max fyra platser per crawl,
100 ms-pacing, global kapacitet, total timeout, stopp och 503 med `Retry-After`.

Två efterföljande omkörningar av den verkliga Sundsvall-källan med den nya
schemaläggaren hämtade samma 355 sidor på 43,86 respektive 40,47 sekunder.
Samtliga sidor var oförändrade, så körningarna gjorde inga embeddinganrop eller
innehållsskrivningar. PostgreSQL och Redis återgick till noll aktiva jobb och
crawlerhälsan var `HEALTHY` utan utgångna leases. Dessa publika nätverkskörningar
bekräftar funktion och terminalisering, men används inte som hastighetsjämförelse
eftersom ursprungswebbplatsens latens varierade mellan körningarna. Den
kontrollerade, alternerade jämförelsen ovan är före/efter-evidensen för
schemaläggaren.

Ett sidgränsfall uppstod när pacing-timern löpte ut efter att `max_pages` redan
hade nåtts: en kvarvarande långsam request kunde då driva en tät
nollsekundsväntan. Ett regressionstest mot den riktiga aiohttp-motorn mätte
3 517 vänteloopar under en 150 ms långsam request före rättningen. Timern rensas
nu när den löper ut, oberoende av om en ny sida får fyllas på. Samma test gör
färre än 20 väntanrop och behåller exakt samma `page_limit`-resultat. De övriga
testerna för pacing, löpande påfyllning och global rättvisa är fortsatt gröna.

### 5. Ta bort eller definiera pausen på 100 ms

`autothrottle_enabled` innebär i dag minst 100 ms paus efter varje fast HTTP-batch, oavsett svarstid eller statuskod. För 60 verkliga Sundsvall-sidor gav samma motor:

| Inställning | Tid | CPU |
| --- | ---: | ---: |
| Fyra samtidiga och 100 ms paus | 5,415–5,592 s | 1,519–1,604 s |
| Fyra samtidiga utan paus | 3,725 s | 1,399 s |
| Åtta samtidiga utan paus | 3,099 s | 1,364 s |

Att bara ta bort pausen var cirka 1,48 gånger snabbare. Samtidighet åtta gav en mindre extra vinst men ökar belastningen på ursprungswebbplatsen och prioriteras inte.

Pausen får inte tas bort genom att låta den befintliga inställningen bli verkningslös. Först behöver produkten bestämma om `autothrottle_enabled` ska betyda fast artighetspaus, adaptiv begränsning eller tas bort till förmån för de redan befintliga reglerna för samtidighet, robots och återförsök.

### 6. Återanvänd exakta embedding-indata inom sidbatchen

Exakt samma embedding-indata förekommer flera gånger i de verkliga korpusarna. Återanvändning endast inom den befintliga, begränsade sidbatchen gav följande möjliga besparing:

| Crawl | Sparade indatatokens | Andel | Packade anrop före/efter vid batch 32 |
| --- | ---: | ---: | ---: |
| 354 sidor | 20 003 | 3,2 % | 133 / 128 |
| 507 sidor | 231 065 | 23,6 % | 196 / 152 |

Nyckeln ska representera den exakta providerindatan och modellens identitet, inklusive exempelvis E5-prefixet. En beräknad vektor fläktas tillbaka till alla ursprungliga chunks, som fortfarande lagras var för sig. Ingen global cache eller återanvändning mellan crawls införs.

## Avvisade eller senarelagda idéer

| Idé | Beslut | Evidens eller skäl |
| --- | --- | --- |
| Kör HTML-extraktion i trådar | Avvisad | Samma 40 svar tog 0,862 s sekventiellt och 1,788 s med fyra trådar; CPU ökade från 0,861 till 2,056 s. |
| Parallella embedding-underbatcher i första ändringen | Avvisad tills ny providerdata finns | En sekventiell 128-grupp matchade tre parallella 32-grupper för den testade modellen och ger enklare felgräns och stopp. |
| Hårdkoda batch 128 för OpenAI eller E5 | Avvisad | Batchgränsen ägs redan av modellens `max_batch_size` och skiljer sig mellan providers och driftsätt. |
| Anpassa batchstorleken efter svarstid | Avvisad | Svarstid är en brusig signal och kan inte visa providerns kapacitetsgräns. Löpande requestplatser ger responsstyrd genomströmning utan en ny regulator. |
| Öka E5-chunks från 200 till 512 tokens | Avvisad som prestandaändring | Det ändrar retrieval och tokenfördelning, inte bara transporteffektivitet. |
| Byt HTML-parser nu | Senarelagd | Dubbel parsning är mätbar CPU-kostnad, men exakt text-, länk- och filbeteende måste jämföras på en större korpus. |
| Byt tokenizer nu | Senarelagd | Direkt cachad tokenizer var 1,54 gånger snabbare i chunkningen men sparade ungefär en sekund på en 507-sidorscrawl. |
| Sitemap-snabbväg för nuvarande crawls | Senarelagd | De två uppmätta webbplatserna använder länkföljande crawl, inte sitemap-läge. |
| Global vektorcache | Avvisad | Betydligt större invaliditets-, säkerhets- och underhållsyta än batchlokal exakt återanvändning. |
| Dela upp den stora importgrafen för att sänka worker-RSS | Senarelagd | Import av crawlmodulerna står redan för merparten av processens cirka 431 MiB. En säker uppdelning är större än de uppmätta temporära vinsterna och påverkar startup/DI brett. |

## Verifiering av den konfigurerade E5-vägen

Den aktiva modellposten för `multilingual-e5-large` använder familjen `e5`,
`max_input=512` och tomt dimensionsfält. Ett isolerat anrop genom Eneos riktiga
modell- och providerlager returnerade tre av tre vektorer med 1 024 dimensioner.
Det visar att prefix, autentisering och provideradaptern fungerar utan en
felaktig `dimensions`-requestparameter.

Den första fulla crawlerkörningen använde testkällan `https://example.com`.
Den nådde aldrig embeddingsteget eftersom värden inte kunde DNS-resolvas från
devcontainern, samtidigt som `sundsvall.se` kunde resolvas och svarade 200.
Körningen gav följande livscykelevidens:

- dispatch efter cirka 24 ms och workerstart efter cirka 0,62 sekunder;
- terminalt `failed/remote_unreachable` efter cirka 3,85 sekunder totalt;
- felorsak `ClientConnectorDNSError` och läsbar detalj "The website could not be reached";
- noll köade eller aktiva PostgreSQL-körningar efter avslut;
- ingen jobb-, resultat- eller in-progress-nyckel kvar i Redis;
- crawlerhälsan `HEALTHY`, med friska executor- och reconciliation-heartbeats,
  noll utgångna leases och noll väntande transportstädningar.

Det verifierar att ett verkligt DNS-fel inte längre lämnar jobbet i kö eller
"pågår".

En andra körning använde en nåbar Sundsvall-sida med samma modell och gick hela
vägen genom hämtning, extraktion, embedding och publicering:

- dispatch efter cirka 16 ms och workerstart efter cirka 0,13 sekunder;
- terminalt `succeeded` efter cirka 0,93 sekunder totalt;
- en publicerad sida på 65 185 byte och noll misslyckade sidor;
- 13 av 13 chunks lagrade i ordning, samtliga med 1 024 dimensioner;
- noll aktiva PostgreSQL-körningar och noll transportkö efter avslut;
- crawlerhälsan åter `HEALTHY` utan utgångna leases eller väntande städning.

Detta är den fulla funktionella E5-verifieringen. Körningen är för liten för
meningsfull CPU-, RSS- eller batchgenomströmningsjämförelse; en större kall crawl
behövs för den delen.

## Genomförandegränser och verifiering

Varje förändring ska kunna granskas och återställas separat.

### Del A: `float32` och korrekt minnesgräns

- Samma antal sidor, chunks och dimensioner.
- Bitidentiska lagrade `float32`-värden för samma providerrespons. Olika
  providerbatcher får bedömas med numerisk och retrievalmässig tolerans eftersom
  den uppmätta modellservern inte är bitinvariant över batchstorlekar.
- Ingen sida eller chunk tappas när minnesgränsen tvingar flera publiceringsvarv.
- RSS jämförs med samma verkliga korpus före och efter.

### Del B: generell request-packning

- Samma chunktexter och ordning som före ändringen.
- `max_batch_size=None` ger fortsatt 32.
- E5-prefix och andra providerprefix appliceras exakt en gång.
- Timeout och global semafor omfattar varje provideranrop.
- Ett fel i underbatch nummer `k` publicerar endast helt färdiga sidor före felgränsen och markerar resten tydligt; inga chunks tappas.
- Två samtidiga crawls får turas om att ta embedding-platser.
- En providers modellgräns höjs först efter en separat mätning för just den modellen och providern.

### Del C: löpande HTTP-platser och pacing

- Samma sidmängd och samma robotsbeteende.
- Högst fyra anrop per crawl och tjugo per workerprocess.
- Långsam och snabb crawl samtidigt, därefter fem långsamma och en snabb.
- DNS-fel, anslutningsfel, långsam respons, 429/503 med återförsök, stopp och total timeout terminaliserar som tidigare.
- Fast 100 ms-paus ändras inte förrän inställningens produktbetydelse är beslutad.

### Del D: batchlokal exakt återanvändning

- Nyckeln byggs från modellidentitet och exakt providerindata.
- Alla ursprungliga chunks lagras med en vektor.
- Token- och requestbesparingen mäts på båda Sundsvall-korpusarna.
- Retrievalresultat jämförs före och efter; identiska indata ska ge samma återanvända vektor inom samma körning.

## Reproducerbarhet och granskningsunderlag

Tabellerna ovan bevarar de råa sammanfattningarna, datamängdernas storlek,
konfigurationen och jämförelsebasen. De tidiga engångsharnessen kördes från
tillfälliga filer och är därför inte en varaktig reproduktionskälla. Mätvärdena
ska inte användas som en CI-tröskel eller ett generellt produktionslöfte.

Den varaktiga regressionsevidensen finns i repositoryts beteendetester:

- den nya HTTP-schemaläggaren gör sidurvalet och länkkön vid `max_pages`
  oberoende av svarslatens, samtidigt som sidhändelser fortsatt levereras i
  den ordning anropen blir klara;
- länkkön bakom en långsam sida är begränsad till två vågor av den befintliga
  samtidighetsgränsen och används inte för crawltyper som inte följer länkar;
- CPU-spin-testet reproducerades rött med 3 517 väntanrop och är grönt under 20;
- float32-vägen gör en riktig PostgreSQL/pgvector-publicering och läser tillbaka
  exakt samma `float32`-värden;
- provider-, retrieval- och delad Datastore-semantik skyddas av de fokuserade
  adapter-, persistence- och API-testerna.

De kontrollerade timing- och RSS-harnessen bör göras till separata körbara
verktyg först om teamet vill följa dessa mått över tid. Det är medvetet inte en
del av runtimeförändringen.
