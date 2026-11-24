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
  image_path: "images/t1.png",
  question: "What is the pump state?",
  public_rules: "RUN off means STOPPED.",
  response_schema: {
    type: "object",
    properties: {
      kind: { type: "string", enum: ["category"] },
      value: { type: "string", enum: ["NORMAL", "LOW_PRESSURE", "STOPPED"] },
    },
  },
};
const numTask: PublicTask = {
  ...catTask,
  task_id: "t2",
  response_schema: {
    type: "object",
    properties: {
      kind: { type: "string", enum: ["numeric"] },
      value_milli: { type: "integer" },
      unit: { type: "string", enum: ["kPa"] },
    },
  },
};

const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("QuestionForm", () => {
  it("validates before sending and shows an accessible error", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    render(<QuestionForm set="demo" task={numTask} />);
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a number/i);
    expect(f).not.toHaveBeenCalled();
  });

  it("submits a tagged answer with an idempotency key and shows the verdict as text", async () => {
    const f = vi.fn(() => Promise.resolve(jsonRes({ task_id: "t1", correct: true }, 201)));
    vi.stubGlobal("fetch", f);
    render(<QuestionForm set="demo" task={catTask} />);
    await userEvent.click(screen.getByRole("radio", { name: "NORMAL" }));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await waitFor(() => expect(screen.getByTestId("outcome-correct")).toHaveTextContent("Correct"));
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/pp/demo/api/v1/attempts");
    expect(JSON.parse(init.body as string)).toEqual({
      task_id: "t1",
      answer: { kind: "category", value: "NORMAL" },
    });
    expect((init.headers as Record<string, string>)["idempotency-key"]).toMatch(/^h-/);
  });

  it("shows an incorrect verdict", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonRes({ task_id: "t1", correct: false }, 201))),
    );
    render(<QuestionForm set="demo" task={catTask} />);
    await userEvent.click(screen.getByRole("radio", { name: "STOPPED" }));
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await waitFor(() => expect(screen.getByTestId("outcome-incorrect")).toBeInTheDocument());
  });

  it("reports offline when the API is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("failed"))),
    );
    render(<QuestionForm set="demo" task={numTask} />);
    await userEvent.type(screen.getByLabelText(/your answer/i), "540");
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await waitFor(() => expect(screen.getByTestId("outcome-offline")).toBeInTheDocument());
  });
});

describe("PanelViewer", () => {
  it("has alt text, zoom controls and draws evidence only when given", async () => {
    const { rerender } = render(<PanelViewer set="demo" task={catTask} label="Panel A" />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/control panel/i);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/pp/demo/api/v1/tasks/t1/image");
    expect(screen.queryAllByTestId("evidence-box")).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: /zoom in panel a/i }));
    expect(screen.getByText("150%")).toBeInTheDocument();
    rerender(
      <PanelViewer
        set="demo"
        task={catTask}
        label="Panel A"
        evidence={[{ instrument_id: "A_gauge_outlet", x: 10, y: 20, width: 100, height: 100 }]}
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
      condition: "C1",
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
