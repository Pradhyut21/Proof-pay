import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportView } from "@/app/reports/ReportView";

describe("run report availability", () => {
  it("explains how to produce a report when the configured directory is empty", () => {
    render(<ReportView data={{ status: "empty" }} />);
    expect(screen.getByRole("heading", { name: "No run reports yet" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("reproduce");
    expect(screen.queryByRole("link", { name: "Download report" })).toBeNull();
  });

  it("shows an explicit failure without a download for invalid reports", () => {
    render(<ReportView data={{ status: "invalid" }} />);
    expect(screen.getByRole("heading", { name: "Report could not be read" })).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("incomplete or invalid");
    expect(screen.queryByRole("link", { name: "Download report" })).toBeNull();
  });
});
