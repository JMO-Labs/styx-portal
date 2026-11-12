import { render, screen } from "@testing-library/react";
import { describe, test, expect } from "vitest";
import { HomeQuotaBanner } from "../home-quota-banner";

const GB = 1024 ** 3;
describe("HomeQuotaBanner", () => {
  test("renders when warn", () => {
    render(<HomeQuotaBanner data={{ used_bytes: 8.5 * GB, quota_bytes: 10 * GB, percent: 85, warn: true }} />);
    expect(screen.getByRole("status").textContent).toContain("Home storage 85 % full (8.5 GB / 10 GB)");
  });
  test("renders nothing when warn is false", () => {
    const { container } = render(<HomeQuotaBanner data={{ used_bytes: GB, quota_bytes: 10 * GB, percent: 10, warn: false }} />);
    expect(container.innerHTML).toBe("");
  });
  test("renders nothing when used_bytes is null or data missing", () => {
    const a = render(<HomeQuotaBanner data={{ used_bytes: null, quota_bytes: null, percent: null, warn: true }} />);
    expect(a.container.innerHTML).toBe("");
    const b = render(<HomeQuotaBanner data={undefined} />);
    expect(b.container.innerHTML).toBe("");
  });
});
