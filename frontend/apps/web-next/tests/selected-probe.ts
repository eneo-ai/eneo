import { luminance, parseColor, type Rgba } from "../src/theme/contrast-math";
import { fold, inPage, ratio, type Kit, type Probe, type Problem } from "./ui-probes";

/*
 * The selected option of every switcher (tab strip, segmented control, toggle group;
 * tests/ui-probes.ts) must be told from its siblings by more than a colour (1.4.1), or by a
 * colour at 3:1 (1.4.11): a plate at 3:1 against what an unselected option shows, an edge or
 * an indicator at 3:1 against the track that only the selected option has, a label or icon
 * colour at 3:1 against the others', or a weight 200 heavier or an underline. That cue rule is
 * reported for review, not failed: light mode marks the selected segment by the label's colour
 * and weight (src/theme/eneo-theme.contrast.test.ts), and no stricter rule is decided. What
 * fails is the decided one: in dark mode a selected plate is lighter than its track, raised,
 * never pressed in (its 3:1 edge is held by the token test).
 */

type Look = {
  plate: string[];
  edges: string[];
  text: string;
  icon: string | null;
  weight: number;
  underline: boolean;
  /** Colours of what is drawn inside (an indicator bar, a dot, a check). */
  marks: string[];
  /** Why the plate cannot be judged (an image or a real gradient), if so. */
  review?: string;
};
type Group = { sig: string; track: string[]; selected: Look; other: Look; review?: string };

function collect(kit: Kit): Group[] {
  const groups = "[role=tablist], [role=radiogroup], [role=group], [role=toolbar]";
  const selected =
    "[aria-selected=true], [aria-checked=true], [aria-pressed=true], [data-state=active], [data-state=on]";
  const look = (item: Element): Look => {
    const plate: string[] = [];
    const review = kit.ownLayers(item, 1, plate);
    const label =
      [...item.querySelectorAll("*")].find(
        (el) =>
          !el.closest("svg") &&
          kit.visible(el) &&
          [...el.childNodes].some((node) => node.nodeType === 3 && node.textContent?.trim())
      ) ?? item;
    const shape = item.querySelector("svg :is(path, circle, rect, line, polyline, polygon)");
    const paintOf = (el: Element) => {
      const s = kit.style(el);
      return kit.rgba(s.stroke !== "none" ? s.stroke : s.fill);
    };
    const marks: string[] = [];
    const shows = (el: Element) => {
      const box = el.getBoundingClientRect();
      if (!box.width || !box.height || kit.style(el).visibility === "hidden") return false;
      for (let node: Element | null = el; node && node !== item; node = node.parentElement)
        if (Number(kit.style(node).opacity) < 0.05) return false;
      return true;
    };
    for (const el of item.querySelectorAll("*")) {
      if ((el.closest("svg") && el.tagName !== "svg") || !shows(el)) continue;
      if (el.tagName === "svg") {
        const inner = el.querySelector("path, circle, rect, line, polyline, polygon");
        if (inner) marks.push(paintOf(inner));
        continue;
      }
      const background = kit.rgba(kit.style(el).backgroundColor);
      if (kit.alpha(background) > 0) marks.push(background);
      marks.push(...kit.edges(el));
    }
    for (const pseudo of ["::before", "::after"]) {
      const s = getComputedStyle(item, pseudo);
      const background = kit.rgba(s.backgroundColor);
      if (s.content !== "none" && Number(s.opacity) > 0.05 && kit.alpha(background) > 0)
        marks.push(background);
    }
    const s = kit.style(label);
    return {
      plate,
      edges: kit.edges(item),
      text: kit.rgba(s.color),
      icon: shape ? paintOf(shape) : null,
      weight: Number(s.fontWeight),
      underline: s.textDecorationLine.includes("underline"),
      marks,
      review
    };
  };
  const found: Group[] = [];
  for (const group of document.querySelectorAll(groups)) {
    if (!kit.visible(group)) continue;
    const items = [
      ...group.querySelectorAll("[role=tab], [role=radio], button[aria-pressed]")
    ].filter((item) => item.closest(groups) === group && kit.visible(item) && !kit.disabled(item));
    const on = items.find((item) => item.matches(selected));
    const off = items.find((item) => !item.matches(selected));
    if (!on || !off) continue;
    const box = group.getBoundingClientRect();
    const paint = kit.paint(group, box.left + box.width / 2, box.top + box.height / 2);
    if (paint.covered) continue;
    const [chosen, other] = [look(on), look(off)];
    const review = paint.review ?? chosen.review ?? other.review;
    found.push({ sig: kit.name(group), track: paint.layers, selected: chosen, other, review });
  }
  return found;
}

const strongOn = (colours: string[], background: Rgba) =>
  colours.filter((colour) => ratio(parseColor(colour), background) >= 3).length;

export const selectedProbe: Probe = async (page, cell) => {
  const problems: Problem[] = [];
  for (const { sig, track: layers, selected: on, other: off, review } of await inPage(
    page,
    collect,
    null
  )) {
    // Paint the probe cannot composite: judging the rest of it would judge a hidden colour.
    if (review) {
      problems.push({ key: `selected ${sig}`, review: true, detail: `not judged: ${review}` });
      continue;
    }
    const track = fold(layers);
    const plate = fold([...layers, ...on.plate]);
    const otherPlate = fold([...layers, ...off.plate]);
    const versus = (a: string, b: string) =>
      ratio(fold([...layers, ...on.plate, a]), fold([...layers, ...off.plate, b]));
    const cues = {
      plate: ratio(plate, otherPlate) >= 3,
      edge: strongOn(on.edges, track) > strongOn(off.edges, track),
      mark: strongOn(on.marks, track) > strongOn(off.marks, track),
      text: versus(on.text, off.text) >= 3,
      icon: !!on.icon && !!off.icon && versus(on.icon, off.icon) >= 3,
      weight: on.weight - off.weight >= 200,
      underline: on.underline !== off.underline
    };
    if (!Object.values(cues).some(Boolean)) {
      problems.push({
        key: `selected ${sig}`,
        review: true,
        detail:
          `the selected option differs by colour only: plate ${ratio(plate, otherPlate)}:1 ` +
          `against an unselected one, label ${versus(on.text, off.text)}:1 (needs 3:1, or a mark)`
      });
    }
    // A plate the eye can see (over 1.05:1) that is darker than the track reads as pressed in.
    if (
      cell.theme === "dark" &&
      ratio(plate, track) > 1.05 &&
      luminance(plate) < luminance(track)
    ) {
      problems.push({
        key: `pressed ${sig}`,
        detail: `the selected plate is darker than its track (${ratio(plate, track)}:1); dark mode raises it`
      });
    }
  }
  return problems;
};
