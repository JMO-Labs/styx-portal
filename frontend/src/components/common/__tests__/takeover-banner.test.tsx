import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TakeoverBanner } from "../takeover-banner";

describe("TakeoverBanner", () => {
  it("renders nothing without a takeover", () => {
    const { container } = render(<TakeoverBanner takeover={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says viewing for view mode", () => {
    render(<TakeoverBanner takeover={{ actor_name: "Ada", mode: "view", started_at: "2026-01-01T00:00:00Z" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Ada is viewing your session");
  });

  it("says controlling for control mode", () => {
    render(<TakeoverBanner takeover={{ actor_name: "Ada", mode: "control", started_at: "2026-01-01T00:00:00Z" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Ada is controlling your session");
  });

  it("has no dismiss control", () => {
    render(<TakeoverBanner takeover={{ actor_name: "Ada", mode: "view", started_at: "2026-01-01T00:00:00Z" }} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
