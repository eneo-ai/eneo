# SharePoint-integration

Den här guiden beskriver hur du konfigurerar SharePoint-integrationen i Eneo. Efter genomförd uppsättning kan användare importera dokument och filer från SharePoint och OneDrive direkt till sina utrymmen i Eneo, med automatisk synkronisering när filer uppdateras.

## Översikt

SharePoint-integrationen gör det möjligt att koppla samman SharePoint-siter och OneDrive-mappar med Eneo. När integrationen är konfigurerad kan användare välja vilka mappar eller siter de vill importera, och Eneo hämtar automatiskt innehållet och håller det uppdaterat via webhooks.

Det finns två olika användningsscenarier att ta hänsyn till:

**Personliga utrymmen** använder OAuth-inloggning där varje användare autentiserar med sitt eget Microsoft-konto. Detta passar när användare vill importera från sin personliga OneDrive eller SharePoint-siter de har tillgång till.

**Delade och organisationsutrymmen** använder istället en central autentisering som konfigureras av administratören. Det innebär att ingen enskild användare behöver logga in med sitt konto för att integrationen ska fungera, vilket undviker problem om en person slutar eller byter roll.

## Förutsättningar

Innan du börjar behöver du:

- Tillgång till Azure Portal med behörighet att registrera applikationer i organisationens Azure AD
- En Eneo-installation med HTTPS (krävs för webhooks från Microsoft)
- Administratörsbehörighet i Eneo

## Skapa en Azure AD-applikation

All kommunikation mellan Eneo och SharePoint sker via Microsoft Graph API, vilket kräver en registrerad applikation i Azure AD.

### Registrera applikationen

Gå till [Azure Portal](https://portal.azure.com) och navigera till **Azure Active Directory** → **App registrations** → **New registration**.

Fyll i följande:
- **Name**: Välj ett beskrivande namn, exempelvis "Eneo SharePoint Integration"
- **Supported account types**: Välj "Accounts in this organizational directory only" om integrationen bara ska användas inom din organisation
- **Redirect URI**: Välj "Web" och ange `https://din-eneo-domän.se/integrations/callback/token/`

Klicka på **Register**.

> **Obs:** Redirect URI måste matcha exakt. Om din Eneo-installation använder en annan bas-URL eller port, anpassa URI:n därefter. Callback-sidan är alltid på `/integrations/callback/token/` och används för alla integrationstyper.

### Konfigurera behörigheter

Efter registrering behöver applikationen rätt behörigheter för att läsa filer från SharePoint. Navigera till **API permissions** → **Add a permission** → **Microsoft Graph**.

Vilka behörigheter som behövs beror på vilken autentiseringsmetod du väljer (se nästa avsnitt), men generellt behövs:

**För delegerade behörigheter (Delegated permissions)**:
- `Files.Read.All` – läsa filer användaren har tillgång till
- `Sites.Read.All` – läsa SharePoint-siter
- `offline_access` – hålla sessionen aktiv utan att användaren behöver logga in igen

**För applikationsbehörigheter (Application permissions)**:
- `Files.Read.All` – läsa filer i hela organisationen
- `Sites.Read.All` – läsa alla SharePoint-siter

Efter att behörigheterna lagts till, klicka på **Grant admin consent** för att godkänna dem på organisationsnivå.

### Skapa en klienthemlighet

Navigera till **Certificates & secrets** → **New client secret**. Ange en beskrivning och välj giltighetstid. Kopiera värdet som visas – det kommer bara visas en gång.

Notera följande värden som behövs för konfigurationen i Eneo:
- **Application (client) ID** – finns på applikationens översiktssida
- **Client secret** – värdet du just kopierade
- **Directory (tenant) ID** eller domännamn – exempelvis `contoso.onmicrosoft.com`

## Välja autentiseringsmetod

Eneo stödjer två metoder för att autentisera mot SharePoint i delade utrymmen. Valet påverkar vilka behörigheter som krävs och hur åtkomstkontrollen fungerar.

### Tjänstekonto (rekommenderas)

Med tjänstekontometoden loggar en administratör in med ett dedikerat Microsoft-konto under konfigurationen. Eneo använder sedan det kontots behörigheter för att läsa filer.

**Fördelar:**
- Detaljerad åtkomstkontroll – Eneo kan bara läsa filer som tjänstekontot har tillgång till
- Inget personberoende – integrationen fortsätter fungera även om den som konfigurerade den slutar
- Tydlig spårbarhet i SharePoints åtkomstloggar

**Kräver:**
- Ett dedikerat tjänstekonto i Azure AD (exempelvis `eneo-service@contoso.com`)
- Kontot måste ha läsbehörighet till de SharePoint-siter som ska importeras
- Delegerade behörigheter i Azure AD-applikationen

### Tenant App

Med tenant app-metoden använder Eneo applikationsbehörigheter som ger tillgång till alla SharePoint-siter i organisationen, utan att någon användare behöver logga in.

**Fördelar:**
- Enklare uppsättning – ingen separat inloggning krävs
- Tillgång till hela organisationens SharePoint

**Nackdelar:**
- Ingen granulär åtkomstkontroll – applikationen kan läsa alla filer
- Kräver att en Azure AD-administratör godkänner applikationsbehörigheter

**Kräver:**
- Application permissions i Azure AD-applikationen
- Admin consent för dessa behörigheter

## Konfigurera integrationen i Eneo

När Azure AD-applikationen är skapad kan du konfigurera integrationen i Eneo.

### Öppna konfigurationen

Logga in i Eneo som administratör och navigera till **Admin** → **Integrationer**. Under SharePoint-kortet, klicka på **Konfigurera**.

### Ange uppgifter

Fyll i formuläret med uppgifterna från Azure AD:

- **Client ID**: Application (client) ID från Azure Portal
- **Client Secret**: Klienthemligheten du skapade
- **Tenant Domain**: Din organisations domän, exempelvis `contoso.onmicrosoft.com`

### Välj autentiseringsmetod

**För tjänstekonto:** Välj "Tjänstekonto" och klicka på "Logga in med Microsoft". Du omdirigeras till Microsofts inloggning där du loggar in med tjänstekontot. Efter inloggning sparas konfigurationen automatiskt.

**För tenant app:** Välj "Tenant App", klicka på "Testa anslutning" för att verifiera att uppgifterna fungerar, och klicka sedan på "Spara".

### Verifiera

När konfigurationen är sparad visas status som "Konfigurerad" på integrationssidan. Användare kan nu börja importera från SharePoint i sina delade utrymmen.

## Webhooks och realtidssynkronisering

För att hålla importerat innehåll uppdaterat använder Eneo Microsoft Graphs webhook-funktionalitet. När en fil ändras i SharePoint skickar Microsoft en notifikation till Eneo som då hämtar den uppdaterade filen.

### Hur webhooks fungerar

När en användare importerar en SharePoint-mapp skapar Eneo en webhook-prenumeration (subscription) hos Microsoft Graph. Microsoft skickar sedan notifikationer till Eneos webhook-endpoint varje gång något ändras i den mappen.

Webhook-prenumerationer har en maximal livslängd på cirka 29 dagar enligt Microsofts begränsningar. Eneo har ett bakgrundsjobb som körs var 12:e timme och automatiskt förnyar prenumerationer som närmar sig utgångsdatum (inom 48 timmar). Under normala omständigheter behöver administratören inte hantera detta manuellt.

### Hantera webhooks

Under **Admin** → **Integrationer** → **Hantera webhooks** kan du se alla aktiva prenumerationer och deras status:

- **Aktiv**: Prenumerationen fungerar normalt
- **Går ut snart**: Prenumerationen går ut inom 48 timmar och kommer förnyas automatiskt vid nästa körning
- **Utgången**: Prenumerationen har gått ut och behöver återskapas

Om webhooks slutat fungera, exempelvis efter ett längre driftstopp där bakgrundsjobbet inte kunnat köra, kan du klicka på **Förnya utgångna** för att manuellt återskapa alla utgångna prenumerationer.

### Felsökning av webhooks

Om ändringar i SharePoint inte synkroniseras:

1. Kontrollera webhook-status i admin-panelen
2. Verifiera att Eneos domän är nåbar via HTTPS från internet
3. Kontrollera att brandväggen tillåter inkommande trafik från Microsofts IP-adresser
4. Granska loggarna för eventuella felmeddelanden

## Felsökning

### Autentisering misslyckas

Om testet av anslutningen misslyckas, kontrollera:

- Att client ID och client secret är korrekt kopierade från Azure Portal
- Att client secret inte har gått ut (de har begränsad giltighetstid)
- Att admin consent har getts för alla behörigheter
- Att rätt behörighetstyp används (delegated för tjänstekonto, application för tenant app)

### Filer synkroniseras inte

Om importerade filer inte uppdateras:

- Kontrollera webhook-status i admin-panelen
- Verifiera att tjänstekontot (vid tjänstekontometoden) fortfarande har tillgång till filerna
- Kontrollera Eneos loggar för felmeddelanden relaterade till SharePoint

### Användare kan inte importera

Om användare får felmeddelanden vid import:

- Verifiera att integrationen är korrekt konfigurerad på organisationsnivå
- Kontrollera att användaren har tillgång till den SharePoint-site de försöker importera från
- Vid personliga utrymmen, be användaren logga ut och in igen för att förnya sin OAuth-token

## Rotera klienthemlighet (Client Secret)

Klienthemligheter i Azure AD har begränsad giltighetstid – vanligtvis mellan 6 månader och 2 år beroende på vad som valdes vid skapandet. När hemligheten går ut slutar integrationen fungera.

### Planera rotation i förväg

Azure AD visar utgångsdatum för klienthemligheter under **Certificates & secrets** i applikationens inställningar. Det rekommenderas att sätta en påminnelse i kalendern minst en vecka innan utgångsdatum för att hinna rotera hemligheten utan avbrott.

### Uppdatera hemligheten

Att uppdatera klienthemligheten påverkar inte befintliga webhook-prenumerationer eller importerad kunskap – det är endast autentiseringsuppgifterna som byts ut.

För att rotera hemligheten:

1. **Skapa ny hemlighet i Azure AD:**
   - Gå till [Azure Portal](https://portal.azure.com) och navigera till din appregistrering
   - Under **Certificates & secrets**, klicka på **New client secret**
   - Ange beskrivning och giltighetstid, klicka sedan **Add**
   - Kopiera den nya hemligheten (den visas bara en gång)

2. **Uppdatera i Eneo:**
   - Navigera till **Admin** → **Integrationer**
   - Klicka på **Konfigurera** under SharePoint
   - Klicka på **Uppdatera secret**
   - Klistra in den nya klienthemligheten
   - Klicka på **Spara**

3. **Verifiera:**
   - Kontrollera att integrationen fortfarande fungerar genom att testa en import eller kontrollera webhook-status

4. **Ta bort gamla hemligheten:**
   - När den nya hemligheten verifierats fungera, gå tillbaka till Azure Portal och ta bort den gamla hemligheten för att undvika säkerhetsrisker

### Vid utgången hemlighet

Om hemligheten redan har gått ut kommer integrationen inte kunna autentisera mot Microsoft Graph. Befintliga webhooks kommer inte ta emot notifikationer och nya importer kommer misslyckas.

Lösningen är densamma som ovan: skapa en ny hemlighet i Azure AD och uppdatera den i Eneo. Efter att den nya hemligheten sparats återupptas normal funktion automatiskt.

## Byta autentiseringsmetod

Om du behöver byta från tjänstekonto till tenant app eller vice versa måste den befintliga konfigurationen först tas bort. Detta beror på att de två metoderna använder olika typer av behörigheter och tokens.

Att ta bort konfigurationen innebär att all importerad SharePoint-kunskap också tas bort. Användare behöver sedan importera sitt innehåll på nytt efter att den nya konfigurationen är på plats.

För att byta metod:
1. Navigera till **Admin** → **Integrationer**
2. Klicka på **Konfigurera** under SharePoint
3. Klicka på **Ta bort integration** och bekräfta
4. Konfigurera integrationen på nytt med den nya metoden
