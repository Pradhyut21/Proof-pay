import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModelAttempts } from "@/components/ModelAttempts";
import { OutcomeBadge } from "@/components/OutcomeBadge";
import { PanelViewer } from "@/components/PanelViewer";
import { QuestionForm } from "@/components/QuestionForm";
import { RunStatus } from "@/components/RunStatus";
import type { PublicTask } from "@/lib/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const catTask: PublicTask = {
  schema_version: "1.0.0",
  task_id: "t1",
  image: "images/t1.png",
  question: "What is the pump state?",
  rules: "RUN off means STOPPED.",
  response_schema: { type: "category", allowed: ["NORMAL", "LOW_PRESSURE", "STOPPED"] },
  set: "dev",
};
const numTask: PublicTask = {
  ...catTask,
  task_id: "t2",
  response_schema: { type: "numeric", unit: "kPa", scale: "milli" },
};

function mockFetch(impl: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => Promise.resolve(impl(url, init))),
  );
}
const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("QuestionForm", () => {
  it("validates before sending and shows an accessible error", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    render(<QuestionForm task={numTask} />);
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a number/i);
    expect(f).not.toHaveBeenCalled();
  });

  it("submits a category answer and shows the outcome with text, not colour only", async () => {
    mockFetch(() => jsonRes({ attempt_id: "a", task_id: "t1", outcome: "correct", status: "ok" }));
    render(<QuestionForm task={catTask} />);
    await userEvent.click(screen.getByRole("radio", { name: "NORMAL" }));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await waitFor(() => expect(screen.getByTestId("outcome-correct")).toHaveTextContent("Correct"));
  });

  it("reports offline when the API is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("failed"))),
    );
    render(<QuestionForm task={numTask} />);
    await userEvent.type(screen.getByLabelText(/your answer/i), "540");
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await waitFor(() => expect(screen.getByTestId("outcome-offline")).toBeInTheDocument());
  });
});

describe("PanelViewer", () => {
  it("has alt text, zoom controls and draws evidence only when given", async () => {
    const { rerender } = render(<PanelViewer task={catTask} label="Panel A" />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/control panel/i);
    expect(screen.queryAllByTestId("evidence-box")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: /zoom in panel a/i }));
    expect(screen.getByText("150%")).toBeInTheDocument();
    rerender(
      <PanelViewer
        task={catTask}
        label="Panel A"
        evidence={[{ pump: "P1", kind: "gauge", box: [10, 20, 110, 120] }]}
      />,
    );
    expect(screen.getAllByTestId("evidence-box")).toHaveLength(1);
  });
});

describe("status components", () => {
  it("labels every outcome with an icon and words", () => {
    for (const o of ["correct", "incorrect", "invalid", "timeout", "offline"] as const) {
      render(<OutcomeBadge outcome={o} />);
      expect(screen.getByTestId(`outcome-${o}`).textContent?.length).toBeGreaterThan(3);
      cleanup();
    }
  });
  it("announces job state and failure detail", () => {
    render(<RunStatus status="failed" error="worker exited 1" />);
    expect(screen.getByRole("status")).toHaveTextContent(/failed/i);
    expect(screen.getByText("worker exited 1")).toBeInTheDocument();
  });
});

describe("ModelAttempts", () => {
  it("always carries the DEMO ONLY label and caps rows at three", () => {
    const mk = (m: string) => ({
      task_id: "t1",
      model: m,
      condition: "C0",
      status: "ok" as const,
      response: { kind: "category" as const, value: "NORMAL" },
    });
    render(
      <ModelAttempts attempts={[mk("a"), mk("b"), mk("c"), mk("d")]} correctAnswer="NORMAL" />,
    );
    expect(screen.getByText(/DEMO ONLY/)).toBeInTheDocument();
    expect(screen.getAllByTestId("outcome-correct")).toHaveLength(3);
  });
  it("shows an offline state instead of attempts", () => {
    render(<ModelAttempts attempts={[]} offline />);
    expect(screen.getByTestId("model-offline")).toBeInTheDocument();
  });
});
