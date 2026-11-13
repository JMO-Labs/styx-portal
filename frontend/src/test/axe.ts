import axe from "axe-core";

/**
 * Assert that `container` has no serious/critical axe violations
 * (WCAG 2.0/2.1 A + AA). Failure message lists rule id and targets.
 */
export async function expectNoSeriousA11y(container: HTMLElement): Promise<void> {
  const results = await axe.run(container, {
    runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    // jsdom has no layout/computed colours, so color-contrast cannot be evaluated.
    rules: { "color-contrast": { enabled: false } },
  });
  const bad = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  if (bad.length > 0) {
    const lines = bad.map(
      (v) =>
        `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
    );
    throw new Error(`Serious/critical a11y violations:\n${lines.join("\n")}`);
  }
}
