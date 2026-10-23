// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { focusAfterRemoval } from "./focus-after-removal";

afterEach(() => {
  document.body.innerHTML = "";
});

function list(names: string[]) {
  const ul = document.createElement("ul");
  for (const name of names) {
    const li = document.createElement("li");
    li.innerHTML = `<a href="/${name}">${name}</a><button type="button">Meny ${name}</button>`;
    ul.append(li);
  }
  document.body.append(ul);
  return ul;
}

const menu = (name: string) =>
  Array.from(document.querySelectorAll("button")).find((b) => b.textContent === `Meny ${name}`)!;

it("names the next row's first control once the row is gone, else the one before it", () => {
  const ul = list(["a", "b", "c"]);
  const middle = focusAfterRemoval(menu("b"));
  expect(middle()).toBeNull();
  ul.children[1]!.remove();
  expect(middle()?.textContent).toBe("c");

  const last = focusAfterRemoval(menu("c"));
  ul.children[1]!.remove();
  expect(last()?.textContent).toBe("a");
});

it("names nothing when the list went with the row, or for a control outside any row", () => {
  const ul = list(["a"]);
  const only = focusAfterRemoval(menu("a"));
  ul.children[0]!.remove();
  expect(only()).toBeNull();

  const button = document.createElement("button");
  document.body.append(button);
  const loose = focusAfterRemoval(button);
  button.remove();
  expect(loose()).toBeNull();
});
