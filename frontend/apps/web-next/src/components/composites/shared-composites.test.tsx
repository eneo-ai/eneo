// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { Bot, Inbox } from "lucide-react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it } from "vitest";
import { ENTITY_TONES, entityAccent, entityTone } from "@/lib/entity-accent";
import { expectNoAxeViolations } from "@/test/axe";
import { EmptyState } from "./empty-state";
import { EntityAvatar, entityInitials } from "./entity-avatar";
import { LoadingState } from "./loading-state";
import { PageHeader } from "./page-header";
import { StatusLabel } from "./status-label";

afterEach(cleanup);

describe("PageHeader", () => {
  it("renders breadcrumbs, the h1, a description and actions", () => {
    render(
      <PageHeader
        title="Medlemmar"
        description="Vilka som har tillgång"
        breadcrumbs={[{ label: "Ytor", href: "/spaces" }, { label: "Min yta" }]}
        actions={<button type="button">Lägg till</button>}
      />
    );
    expect(screen.getByRole("heading", { level: 1, name: "Medlemmar" })).toBeTruthy();
    expect(screen.getByText("Vilka som har tillgång")).toBeTruthy();
    const trail = screen.getByRole("navigation");
    expect(within(trail).getByRole("link", { name: "Ytor" }).getAttribute("href")).toBe("/spaces");
    expect(within(trail).getByText("Min yta").closest("[aria-current='page']")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Lägg till" })).toBeTruthy();
  });

  it("keeps the legacy children actions slot", () => {
    render(
      <PageHeader title="Appar">
        <button type="button">Skapa</button>
      </PageHeader>
    );
    expect(screen.getByRole("button", { name: "Skapa" })).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});

describe("EmptyState", () => {
  it("renders the title as a heading with legacy children as actions", () => {
    render(
      <EmptyState title="Inga appar ännu" description="Skapa en app för att komma igång">
        <button type="button">Skapa app</button>
      </EmptyState>
    );
    expect(screen.getByRole("heading", { level: 2, name: "Inga appar ännu" })).toBeTruthy();
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Skapa app" })).toBeTruthy();
  });

  it("skips the actions row for a falsy permission-gated slot", () => {
    const { container } = render(<EmptyState title="Tomt">{false}</EmptyState>);
    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container.textContent).toBe("Tomt");
  });
});

describe("LoadingState", () => {
  it("is a busy status region with a translated label", () => {
    render(
      <NextIntlClientProvider locale="sv" messages={{ loading: "Laddar..." }}>
        <LoadingState rows={2} />
      </NextIntlClientProvider>
    );
    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-busy")).toBe("true");
    expect(within(region).getByText("Laddar...")).toBeTruthy();
  });
});

describe("EntityAvatar", () => {
  it("derives initials from the first two words", () => {
    expect(entityInitials("Ärende hantering Sundsvall")).toBe("ÄH");
    expect(entityInitials("  eneo ")).toBe("E");
  });

  it("uses a deterministic categorical tone per id", () => {
    expect(entityTone("space-1")).toBe(entityTone("space-1"));
    expect(ENTITY_TONES).toContain(entityTone("space-1"));
    const { container } = render(<EntityAvatar id="space-1" name="Min yta" />);
    const tile = container.firstElementChild!;
    for (const cls of entityAccent("space-1").split(" ")) {
      expect(tile.classList.contains(cls)).toBe(true);
    }
    expect(tile.getAttribute("aria-hidden")).toBe("true");
    expect(tile.textContent).toBe("MY");
  });

  it("is an image with an accessible name when labelled", () => {
    render(<EntityAvatar name="Min yta" label="Min yta" tone="teal" />);
    expect(screen.getByRole("img", { name: "Min yta" })).toBeTruthy();
  });
});

describe("StatusLabel", () => {
  it("reads the label once; the dot is decorative", () => {
    const { container } = render(<StatusLabel status="success" label="Publicerad" />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(container.textContent).toBe("Publicerad");
  });
});

// WCAG 2.2 A/AA (ACCESSIBILITY.md): every shared composite, in the variants
// screens use, renders without axe violations.
describe("accessibility", () => {
  it("PageHeader with breadcrumbs, description and actions", async () => {
    const { container } = render(
      <PageHeader
        title="Medlemmar"
        description="Vilka som har tillgång"
        breadcrumbs={[{ label: "Ytor", href: "/spaces" }, { label: "Min yta" }]}
        actions={<button type="button">Lägg till</button>}
      />
    );
    await expectNoAxeViolations(container);
  });

  it("EmptyState, framed and compact, with an icon and actions", async () => {
    const { container } = render(
      <>
        <EmptyState
          title="Inga appar ännu"
          description="Skapa en app för att komma igång"
          icon={<Inbox />}
          actions={<button type="button">Skapa app</button>}
        />
        <EmptyState title="Inga träffar" headingLevel={3} isCompact framed={false} />
      </>
    );
    await expectNoAxeViolations(container);
  });

  it("LoadingState in both variants", async () => {
    const { container } = render(
      <NextIntlClientProvider locale="sv" messages={{ loading: "Laddar..." }}>
        <LoadingState rows={2} />
        <LoadingState variant="text" label="Laddar svar" />
      </NextIntlClientProvider>
    );
    await expectNoAxeViolations(container);
  });

  it("EntityAvatar decorative, labelled, with an image and with an icon", async () => {
    const { container } = render(
      <>
        <EntityAvatar id="space-1" name="Min yta" />
        <EntityAvatar name="Min yta" label="Min yta" tone="teal" size="lg" />
        <EntityAvatar name="Assistent" label="Assistent" src="/icon.png" size="xl" />
        <EntityAvatar name="Assistent" icon={<Bot />} size="sm" />
      </>
    );
    await expectNoAxeViolations(container);
  });

  it("StatusLabel in every tone, pulsing and static", async () => {
    const { container } = render(
      <>
        <StatusLabel status="success" label="Publicerad" />
        <StatusLabel status="warning" label="Utkast" />
        <StatusLabel status="error" label="Fel" />
        <StatusLabel status="accent" label="Synkar" isPulsing />
        <StatusLabel status="neutral" label="Inaktiv" />
      </>
    );
    await expectNoAxeViolations(container);
  });
});
