# Byggspec — AI-byggaren

Exakta värden för implementationen. CSS-pixlar vid 1×, ljust läge. Där ett värde skiljer sig mellan bredder står brytpunkten i noten.

Källa: `AI-byggaren.dc.html`, fliken **Spec** (och **Mått**-blocket i noteringspanelen per skärm).

---

## 1. Stagen — den grå ytan

Den grå ytan ska läsas som ett rum, inte som ett kort. I nuvarande bygge är den indragen till vänster men går ut i kant nedåt och åt höger, så bara ett hörn syns — det är därför den ser avklippt ut. Välj helbleed (rekommenderat) och ta bort alla hörn och indrag.

| Egenskap | Värde | Regel |
| --- | --- | --- |
| Bakgrund | `var(--background-secondary)` | Soil-50. Panelen ovanför är `--background-primary`. |
| Vänsterkant | `left: 0` mot sidofältets kant | Inget `margin-left`, ingen padding på föräldern, ingen `border-left`. |
| Övre kant | `border-top: 1px solid var(--border-default)` | Hårstrecket går hela panelbredden — från sidofältets kant till höger kant. |
| Hörn | `border-radius: 0` | Alla fyra. Ett radie-värde här är felet i bygget. |
| Höjd | `flex: 1; min-height: 0` | Föräldern måste ha fast höjd, annars blir ingen scrollcontainer och sticky-foten släpper. |
| Scroll | `overflow-y: auto` på stagen | Aldrig på body. Sidofält och rubrik ska stå still. |
| Padding | `24px 28px 40px` | 20px sidor under 1024px, 16px under 768px. |
| Alternativ: kortläge | inset 24px, radius 12px | Bara om alla fyra hörn syns — och foten måste då ligga inne i kortet. |

## 2. Rutnät och centrering

Fasraden, utkaststatusen, Samtal-knappen och innehållet ska dela EN container. I bygget står första fas-pipen cirka 320px till vänster om kortets kant, vilket får raden att sväva.

| Yta | Kolumnbredd | Regel |
| --- | --- | --- |
| Frågor / Bekräfta / Bygger | `max-width: 660px` | Centrerad: `margin-inline: auto`. |
| Ny uppgift | `max-width: 650px` | Rubrik, fält och exempel i samma kolumn. |
| Granska planen | `max-width: 860px` | Stegkedjan inuti kortet: `max-width: 760px`. |
| Flöden (lista) | `max-width: 1060px` | Tabellen fyller kolumnen. |
| Fasrad + statusrad | samma max-width som innehållet | Första pipens vänsterkant = kortets vänsterkant. |
| Sticky fot | samma max-width, centrerad | Fotens innehåll ligger i containern, bakgrunden går helbleed. |

## 3. Komponentmått

Höjder är exakta, inte minsta värden. Samtal-knappen i bygget är högre och rundare än resten av verktygsraden — den ska följa samma mått som övriga sekundärknappar.

| Komponent | Mått | Detalj |
| --- | --- | --- |
| Samtal-knapp | `h 32 · pad 0 12 · r 8 · gap 7` | Ikon 15px, etikett 12.5/600, räknare 18×18 r999 11/700 på `--background-tertiary`. Mobil: h 44. |
| Primärknapp | `h 36 · pad 0 16 · r 8` | 13/600, `--accent-default`, text `--text-on-fill`. Mobil: h 44, 100% bredd, 14/600. |
| Sekundärknapp | `h 36 · pad 0 13 · r 8` | 1px `--border-default` på `--background-primary`. |
| Ghost (Bifoga filer) | `h 32 · pad 0 10 · gap 7` | Ikon 15px, 12.5/500, färg `--text-secondary`; hover ger `--background-secondary`. |
| Fas-pip | `22×22 · border 1.5 · r 50%` | Siffra 11/700. Aktiv etikett 13/700 i chip `pad 4 10 r 8`. |
| Fas-linje | `flex 0 1 84 · h 1 · margin 0 10` | Klar = `--accent-default`, kommande = `--border-default`. |
| Kort | `r 12 · border 1px` | Rubrikdel pad 16–20, kropp 18–20, fot 13 20. |
| Svarsalternativ | `min-h 44 · pad 12 · r 10 · gap 12` | Prick 19×19 border 1.5, fyllning 7×7. Valt: 1px `--accent-default` + 6% ton. |
| Badge «Eneo föreslår» | `h 20 · pad 0 8 · r 999` | 10.5/700, letter-spacing .03em, `--accent-dimmer` på `--accent-stronger`. |
| Svarschip | `h 30 · pad 0 11 · r 999` | 12.5px. Ändra-länken 12.5/600 i `--accent-default`. |
| Förloppsmätare | `180×3 · r 2` | Fyllning `--accent-default`, spår `--background-tertiary`. |
| Segmenterad kontroll | `pad 3 · r 9 · item pad 5 12 r 7` | 12.5/600. Valt: `--background-primary` + `--shadow-default`. |
| Modellbricka | `11.5/500` dämpad text | Ingen fylld grå pill — den tar över steget. Kolumn 150px, krymper till 88px. |
| Composer | `r 12 · pad 13 · border 1px` | Textarea 14.5/1.55, 3 rader, min-h 96. Fokus: 1px `--accent-default`. |
| Skelettrad | `min-h 58 · pad 12 13 · r 10` | Staplar 11px och 9px höga, r 4, gap 7, animation 1.6s. |
| Sticky fot | `pad 12 28 · border-top 1px` | `--color-white` 94% + blur 10px. Mobil: pad 11 14, knappar staplade. |

## 4. Typografi

En skala per elementklass. Inget under 12px, och sekundärtext aldrig ljusare än `--text-secondary`.

| Roll | Storlek | Användning |
| --- | --- | --- |
| Sidrubrik | 19px / 800 / -.02em | AI-byggaren i panelhuvudet. |
| Skärmrubrik | 27px / 800 / -.03em | «Vad ska flödet göra?» Bara på Ny uppgift. |
| Kortrubrik | 19px / 700 / -.02em | Frågans text. Bekräftelsekortet: 17px / 700. |
| Plantitel | 22px / 800 / -.025em | Flödets namn i Granska. |
| Brödtext | 14.5px / 1.55 | Inledningar och sammanfattningen. |
| Sekundär | 13px / 1.6 | «Därför frågar jag», beskrivningar. |
| Meta | 12.5px | Statusrader, fotnoter, chips. |
| Mikro | 11.5px / 600 | «Fråga 2 av 3», kolumnrubriker, modellbricka. |

## 5. Brytpunkter

Fyra steg. Godkännandet ska fungera på 375px eftersom det ofta sker i telefon.

| Bredd | Layout | Vad som ändras |
| --- | --- | --- |
| ≥ 1280px | kolumn på max-bredd | Fasrad vågrät med hela etiketter. Modellkolumn 150px. |
| 1024–1279px | kolumn = 100% − 56px | Modellkolumn krymper till 88px, brickor kortas med ellips och tooltip. Stegnamnet har golv 96px. |
| 768–1023px | sidofält 56px, bara ikoner | Stage-padding 20px. Fasetiketter kortas till Förstå / Utforma / Granska. |
| < 768px | en kolumn | Fasrad blir en rad: «Steg 1 av 3 · Vi förstår din uppgift» 13/600. Samtal blir 44px. Beslutsrader staplas: etikett 12px över värdet. |
| < 375px | ingen vågrät scroll | Diagrammet står kvar lodrätt, noderna får pad 10 11. |
| Rörelse | 150–220ms ease-out | Skelett 1.6s. `prefers-reduced-motion` tar bort allt utom opacitet. |

## 6. Mått per skärm

| Skärm | Nyckelmått |
| --- | --- |
| Flöden | kolumn 1060px · radhöjd 44px (13px pad) · namnkolumn `minmax(320px,4fr)` · statusbricka h 22 r 999 · primärknapp h 34 r 8 |
| Skapa (dialog) | bredd `min(100%,520px)` · radie 14px · textarea 3 rader r 9 · exempelchip h 29 r 999 · fot pad 13 24 |
| Ny uppgift | kolumn 650px · rubrik 27/800 · composer r 12 pad 13 · Bifoga filer h 32 ikon 15 · Skicka h 34 pad 0 15 |
| Frågor | kolumn 660px · mätare 180×3 r 2 · alternativ min-h 44 pad 12 · prick 19 (fyllning 7) · badge h 20 10.5/700 · svarschip h 30 r 999 |
| Bekräfta | kolumn 700px · beslutsrad `grid 200px 1fr auto` · Ändra h 30 pad 0 10 · fältchip h 26 r 999 · fot pad 13 20 |
| Bygger | kolumn 700px · skelettrad min-h 58 r 10 · staplar 11px och 9px r 4 · puls 1.6s · nummerbricka 24×24 r 7 |
| Granska | kolumn 860px · stegkedja max 760px · nod pad 13 14 r 10 · modellkolumn 150→88px · kopplare 1×14px centrerad · fot pad 12 28 |
| Mobil | ram 375px · primärknapp h 44 100% · Samtal h 44 · fasrad en rad 13/600 · stage-padding 14px |

---

## 7. Avvikelser i nuvarande bygge

Läst ur skärmbilderna från implementationen. Ordnat efter hur mycket det påverkar förståelsen, inte efter hur svårt det är att rätta. `geometri` och `fel` först.

1. **Grå ytan har ett hörn** *(geometri)* — Stagen är indragen ~30px till vänster och har ett skarpt övre vänsterhörn, medan höger och nedre kant går ut i skärmkanten. Ytan läses som ett kort som råkat bli avklippt.
   **Ska vara:** helbleed — vänsterkanten möter sidofältets kant, `border-radius: 0`, ett hårstreck på ovansidan i full bredd. Eller kort med 24px marginal på alla fyra sidor och radius 12px — men då måste foten ligga inne i kortet.

2. **Fasraden är inte i rutnätet** *(geometri)* — Fas-pipen och «utkastet sparas automatiskt» börjar cirka 320px till vänster om kortets kant. Ingen av raderna delar container med innehållet.
   **Ska vara:** en container per skärm (660 / 860 / 1060px, centrerad). Första pipens vänsterkant ska ligga exakt på kortets vänsterkant.

3. **Blå ram runt frågans rubrik** *(fel)* — Rubriken «Vad ska flödet producera som slutresultat?» har en blå ram — en fokusring på ett element som inte går att fokusera.
   **Ska vara:** ta bort ramen från rubriken. Flytta fokus till radiogruppen vid inträde och behåll `:focus-visible` bara på knappar och alternativ.

4. **«Fråga 1» saknar antal och mätare** *(innehåll)* — Rubriken säger «Fråga 1» utan totalen, så användaren vet inte om det kommer tio frågor.
   **Ska vara:** «Fråga 1 av 3» i 11.5/600 plus mätaren 180×3px till höger om texten.

5. **Alternativens exempel visar användarens egna ord** *(innehåll)* — Under det föreslagna alternativet står «Du skrev “Jag vill transkribera en ljudfil.”» — det förklarar varför alternativet föreslås, inte vad valet ger.
   **Ska vara:** två separata rader — exemplet på resultatet («Ger t.ex. Motesrapport-2026-08-16.pdf») på varje alternativ, och skälet bara på det föreslagna.

6. **«Eneo föreslår» är blå text** *(stil)* — Förslaget står som blå text intill etiketten och läses som en länk.
   **Ska vara:** badge — h 20, pad 0 8, r 999, 10.5/700 versalt, `--accent-dimmer` på `--accent-stronger`.

7. **Bekräftelsen dubblerar rader** *(innehåll)* — «Indata vid körning» + «Indata», och «Slutresultat» + «Utdata», står som fyra rader med samma två värden.
   **Ska vara:** tre rader — Syfte, Indata, Slutresultat. «Planerad bearbetning» är den enda härledda raden.

8. **Dina svar är markerade som härledda** *(fel)* — Syfte och Indata har «följer av dina svar» trots att de ÄR dina svar — bara Slutresultat går att ändra.
   **Ska vara:** alla tre svaren får Ändra (sekundärknapp h 30, pad 0 10, r 8). «följer av dina svar» hör bara till Planerad bearbetning.

9. **Föräldralös metadata-rad** *(innehåll)* — «Metadata vid körning: Inga extra fält» ligger utanför både beslutslistan och antagandena.
   **Ska vara:** antingen som antagande, eller strykt. Ingenting utanför en rubrik på bekräftelsekortet.

10. **Två olika väntetillstånd** *(innehåll)* — Ett läge visar «Eneo läser…» med två staplar, ett annat femradsskelettet. Användaren möter två olika svar på samma fråga.
    **Ska vara:** ett skelett från första millisekunden, radantal = förväntat antal steg, med den tysta berättarraden under rubriken.

11. **Kortet ligger i överkant på en tom yta** *(geometri)* — På Ny uppgift och Bygger står kortet högt upp med runt 1000px tom grå yta under.
    **Ska vara:** stagens innehåll får `min-height: 100%` och centreras lodrätt när det är kortare än ytan; foten sitter i underkant.

12. **Modellbrickan är för stark** *(stil)* — Fylld grå pill med 12px text väger lika mycket som stegets namn.
    **Ska vara:** 11.5/500 dämpad text, eller pill med 1px kant utan fyllning. Modell ska gå att se, inte läsas först.

13. **Bekräftelsen saknar innehållslistan** *(innehåll)* — Chipsen för «Innehåll som rapporten ska bevara» finns inte, så användaren ser inte vilka fält rapporten ska täcka.
    **Ska vara:** chips h 26, pad 0 10, r 999, 12.5px, gap 6 — under beslutslistan.

---

## 8. Ordval som inte får glida

- **stegredigeraren** — enda namnet på platsen där modell ändras. Inte «steginställningar».
- **utkast** — flödet skapas som utkast och är inte igång förrän det publiceras.
- Modellen får **ses** per steg, aldrig ändras från chatten.
- «Inget skapas förrän du godkänner» — samma mening i alla tre faser.

---

# Del 2 — Ändringsläge (ändra ett publicerat flöde)

Samma tre faser och samma mått som i del 1. Det som byts är **ord, löften och kontroller**, eftersom flödet redan finns, körs skarpt, och andra saker hänger på det. Skärmarna finns i prototypen under flikarna **Ändra · Ändringsfråga · Ändringen · Diff**.

## 9. Vad som skiljer mot att skapa

| Yta | Värde | Regel |
| --- | --- | --- |
| Sidhuvud | flödesnamn + `Publicerad · v3` h 22 r 999 (shadcn `Badge variant="outline"`, `CheckCircle2` size-3, positive-dimmer/60 + positive-default/25) | **Tre** sekundärknappar h 32, alla kvar: Kör flöde · Redigera · Avpublicera. Ingen av dem blir blå under en ändring — skärmens enda primär hör till ändringen. Ta inte bort Redigera. |
| Flikrad | `pad 8 12 · border-bottom 2px` | Byggare / Historik / AI-byggaren. Aktiv: 13/700 + `--accent-default`. |
| Statusrad under flikarna | en rad: status vänster, `Börja om` + `Samtal` höger | **Ingen andra rubrik och ingen andra bakåtpil.** Flödesrubriken äger titeln; en «AI-byggaren»-rubrik här upprepar bara den aktiva fliken. Två bakåtpilar med samma `aria-label` går inte att skilja åt med skärmläsare. |
| `Börja om` | h 30 · pad 0 11 · r 8 · sekundär | Kastar ändringsutkastet — därför en bekräftelse: «Kasta ändringen och börja om? Utkastet med dina svar tas bort. Den publicerade versionen v3 påverkas inte och fortsätter köras.» Bekräftelseknappen är `--negative-default`. Samma sak gäller den smala radens bakåtlänk i fas 1: den heter «Kasta ändringen», inte «Avsluta». |
| Versionskort | `pad 14 16 · r 12` | «NUVARANDE VERSION» 11.5/600 versalt, sedan steg/in-ut 13.5/600, körningar 12px. |
| Notis om drift | `pad 11 13 · r 10 · ikon 15` | `--accent-dimmer`. Texten: den publicerade versionen fortsätter köras. |
| Fasetiketter | samma mått | «Eneo förstår ändringen» / «utformar ändringen» / «granskar innan den publiceras». |
| «Används i dag» | `h 20 · pad 0 8 · r 999` | `--positive-dimmer` på `--positive-stronger`. Ersätter «Eneo föreslår» på nuvarande värde. |
| Konsekvenspanel | `pad 14 18` · warning-dimmer | Visas bara när valt värde ≠ nuvarande. Innehåller återställningsknapp h 32. |
| Diffräknare | `h 26 · pad 0 10 · r 999 · punkt 7` | nytt = positive, ändrat = accent, oförändrat/borttaget = soil-50. |
| Före/efter-block | `r 8 · border-left 3px · pad 10 12` | FÖRE grå (`--border-stronger`), EFTER blå (`--accent-default`). Etikett 11/700 versalt. |
| Oförändrat stegkort | soil-50 · border-dimmer · namn 14/500 | Ingen expandering, ingen chevron, `cursor: default`. |
| Fot i diffen | 3 knappar h 36 | Be om en ändring · Spara som utkast (sekundära) · Publicera ändringen (primär). |

### Mått per ändringsskärm

| Skärm | Nyckelmått |
| --- | --- |
| Ändra | kolumn 660px · versionskort pad 14 16 r 12 · notis pad 11 13 r 10 ikon 15 · rubrik 27/800 · ändringschip h 30 r 999 |
| Ändringsfråga | kolumn 660px · «Används i dag» h 20 10.5/700 · konsekvenspanel pad 14 18 · Behåll-knapp h 32 pad 0 12 · alternativ min-h 44 r 10 |
| Ändringen | kolumn 700px · beslutsrad `grid 200px 1fr auto` · orörd-chip h 26 r 999 · fot pad 13 20 |
| Diff | kolumn 860px · räknarchip h 26 r 999 (punkt 7) · före/efter border-left 3px r 8 · oförändrat kort soil-50 · fot pad 12 28 med 3 knappar |

## 10. Avvikelser i ändringsläget

Läst ur skärmbilderna av det byggda ändringsläget. De två första är de allvarliga.

1. **Frågan rekommenderar bort nuvarande värde** *(fel)* — Flödet tar i dag emot ljud, men frågan «Vilket material ska flödet ta emot vid körning?» har **Dokument** förvalt och märkt «Eneo föreslår». Ett klick på Bekräfta byter flödets indata och tar bort transkriberingssteget.
   **Ska vara:** i ändringsläge är nuvarande värde förvalt och märkt «Används i dag» (h 20, `--positive-dimmer`). «Eneo föreslår» används bara på frågor som inte redan är besvarade av flödet. Väljs ett annat värde visas en konsekvenspanel med vad som tas bort och vilka appar som berörs, plus en knapp som återställer.

2. **Två löften som motsäger varandra** *(fel)* — Överst står «utkastet sparas automatiskt», i inledningen «Inget sparas innan dess». Båda syns samtidigt på samma skärm.
   **Ska vara:** ett löfte per läge. I ändringsläge: «Den publicerade versionen fortsätter att köras medan du arbetar. Din ändring påverkar ingen förrän du publicerar den.» Autosparningen beskrivs som *utkast*, aldrig som «inget sparas».

3. **Ändringsläget visar inte nuläget** *(innehåll)* — Skärmen frågar vad som ska ändras utan att visa vad flödet gör i dag: inga steg, inget in/ut, ingen körningsvolym.
   **Ska vara:** ett versionskort före frågan — «5 steg · ljud in, PDF ut», körningar senaste 30 dagarna, antal appar som använder flödet, och «Visa nuvarande plan» som sekundärknapp.

4. **Fasorden talar om att skapa** *(innehåll)* — «Du granskar innan det skapas» står kvar när ett publicerat flöde ändras.
   **Ska vara:** «Eneo förstår ändringen» → «Eneo utformar ändringen» → «Du granskar innan den publiceras».

5. **Ingen diff efter ändringen** *(innehåll)* — Planen visas om i sin helhet utan markeringar, så användaren måste jämföra sex steg mot minnet.
   **Ska vara:** diff med fyra räknare (nytt/ändrat/oförändrat/borttaget), oförändrade steg nedtonade i soil-50, ändrade steg med före/efter-block, och kryssrutan «Visa bara det som ändras» (av som standard).

6. **Kör flöde är blå under en pågående ändring** *(stil)* — Sidhuvudets primärknapp kör den publicerade versionen medan användaren är mitt i en ändring — två primära åtgärder på skärmen.
   **Ska vara:** Kör flöde blir sekundär h 32 så länge ett ändringsutkast finns. Skärmens enda blå knapp hör till ändringen.

7. **Påverkan syns aldrig** *(innehåll)* — Ingenting säger att två appar och en assistent använder flödet.
   **Ska vara:** egen sektion «Vad ändringen påverkar» före foten, med en rad per app/assistent och «Byter till v4». Publiceringsdialogen upprepar det och nämner att v3 sparas i Historik och kan återställas.

8. **«Börja om» ligger bredvid Samtal utan konsekvens** *(innehåll)* — En textlänk som kastar hela ändringen, i samma vikt som en navigering.
   **Ska vara:** behåll platsen men gör den till en sekundärknapp h 30 med bekräftelse: «Kasta ändringen och börja om? Utkastet med dina svar tas bort. Den publicerade versionen v3 påverkas inte och fortsätter köras.» Kastaknappen i `--negative-default`.

9. **Dubbel sidrubrik i ändringsläget** *(geometri)* — Ändringsläget ärver skapandelägets rubrikrad, så skärmen får två `h1` («Strukturerad samtalsrapport» och «AI-byggaren»), två bakåtpilar med identisk `aria-label`, och nästan dubbel höjd på sidhuvudet innan innehållet börjar.
   **Ska vara:** i ändringsläge visar raden under flikarna bara utkaststatus till vänster och `Börja om` + `Samtal` till höger. Rubrik och bakåtpil hör till flödesrubriken. Skapandeläget behåller sin rubrikrad oförändrad.

## 11. Ordval i ändringsläget

- **publicera**, inte «skapa» — ingenting skapas när ett befintligt flöde ändras.
- **utkast** = opublicerade ändringar på ett levande flöde. Säg aldrig «inget sparas» i samma vy.
- **v3 → v4** — versionen namnges i sidhuvud, i diffens etikett och i publiceringsdialogen.
- **Används i dag** — märkningen för nuvarande värde i frågor. Aldrig «Eneo föreslår» på ett värde som redan gäller.
- «Den publicerade versionen körs oförändrad» — samma mening i frågefoten och i diffens fot.

## 12. Ordning att bygga i

1. Löftesraden och versionskortet på Ändra-skärmen (avvikelse 2 och 3) — de kostar minst och tar bort mest oro.
2. Nuvarande värde förvalt i frågor + konsekvenspanelen (avvikelse 1) — den enda som kan orsaka skada i drift.
3. Fasorden (avvikelse 4) — ren textändring.
4. Diffen (avvikelse 5) — störst arbete, störst effekt på förståelsen.
5. Påverkanssektionen och publiceringsdialogen (avvikelse 7).
6. Kör flöde-knappens vikt och «Börja om»-bekräftelsen (avvikelse 6 och 8).

## 13. Kontrollerat mot koden — läs detta innan du bygger

Grundat i `routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte` och `components/FlowVersionBadge.svelte`, inte i skärmbilderna.

- **Sidhuvudet har tre sekundärknappar när flödet är publicerat:** `Kör flöde` · `Redigera` (`m.edit()`) · `Avpublicera` (`m.flow_unpublish_confirm_action()`). Behåll alla tre.
- **`Redigera` går inte till stegredigeraren direkt.** I koden sätter den `unpublishIntent = "edit"` och öppnar avpubliceringsdialogen; bekräftelseknappen heter `flow_unpublish_and_edit_action()`. Ett publicerat flöde är alltså läsbart men inte redigerbart (`m.flow_published_readonly()`, `disabled={$isPublished}` på namn, beskrivning, transkribering och formulärschema).
- **Konsekvens för texten i planen:** «ändras i stegredigeraren» är sant men ofullständigt. Skriv «ändras i stegredigeraren — kräver att flödet avpubliceras». Annars skickas användaren mot en vägg.
- **Det här är hela argumentet för AI-vägen i ändringsläget:** den tar fram ändringen medan flödet fortfarande är i drift, och avpublicering behövs först vid publiceringen. Säg det i gränssnittet, en gång, på Ändra-skärmen.
- **Versionsbrickan är redan byggd.** Använd `FlowVersionBadge` (den har en 600 ms scale/ring-puls när versionen byter) — bygg ingen ny bricka för v3 → v4.
- **Fliken lever i URL:en** (`?tab=builder|history|ai-builder`, `tabIdPrefix="flow-detail-tab"`). En ändring som pågår får inte tappas när användaren byter flik och tillbaka.
