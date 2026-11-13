import { describe, expect, it } from "vitest";
import { expectNoSeriousA11y } from "./axe";

function mount(html: string): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
}

describe("expectNoSeriousA11y", () => {
  it("fails on a button with no accessible name", async () => {
    const el = mount("<button></button>");
    await expect(expectNoSeriousA11y(el)).rejects.toThrow(/button-name/);
  });

  it("passes on a named button", async () => {
    const el = mount("<button>OK</button>");
    await expect(expectNoSeriousA11y(el)).resolves.toBeUndefined();
  });
});
