import { expect, test } from "@playwright/test";

const semanticPair = "p_784449ff7096f562";
const nuisancePair = "p_114a1f1fc1ae6b9c";
const baseTask = "t_4ca4005a1f640860";

test("judge flow: generate -> view -> answer -> compare -> reveal", async ({ page }) => {
  // Overview shows the API is up.
  await page.goto("/");
  await expect(page.getByTestId("api-ready")).toBeVisible();

  // Generate with the real Python worker and serve the result from Axum.
  await page.goto("/factory");
  await page.getByLabel("Seed").fill("judge-rehearsal");
  await page.getByLabel(/Number of panels/).fill("2");
  await page.getByRole("button", { name: "Generate" }).click();
  await expect(page.getByTestId("run-status")).toContainText("Succeeded", { timeout: 90_000 });
  // Each base scene yields several tasks; the page shows at most four.
  await expect(page.locator("figure").first()).toBeVisible();
  expect(await page.locator("figure").count()).toBeLessThanOrEqual(4);

  // Invalid answer is rejected client-side with an accessible message.
  await page.getByRole("button", { name: "Submit answer" }).first().click();
  await expect(page.getByRole("alert").first()).toBeVisible();

  await page.getByRole("link", { name: "Inspect evidence" }).first().click();
  await page.getByRole("button", { name: "Reveal evidence" }).click();
  await expect(page.getByTestId("inspector-raster-status")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Generator reading" })).toBeVisible();
  await expect(page.getByTestId("raster-evidence-box")).toHaveCount(2);
  if (process.env.PANELPROOF_RUST_PP) {
    await expect(
      page.getByText("The independent Rust rule result agrees with Python."),
    ).toBeVisible();
  }

  // Counterfactual pair compare + a human attempt + reveal.
  await page.goto("/arena");
  const pair = page.getByLabel("Counterfactual pair");
  await pair.selectOption(semanticPair);
  await expect(page.getByTestId("variant-compare").locator("figure")).toHaveCount(2);
  await page.getByRole("radio").first().check();
  await page.getByRole("button", { name: "Submit answer" }).first().click();
  await expect(page.locator('[data-testid^="outcome-"]').first()).toBeVisible();
  await expect(page.getByText(/DEMO ONLY/).first()).toBeVisible();
  await page.getByRole("button", { name: /Reveal answers/ }).click();
  await expect(page.getByTestId("revealed-answer")).toHaveText([
    "Correct answer: NORMAL",
    "Correct answer: LOW_PRESSURE",
  ]);
  await expect(page.getByTestId("evidence-box").first()).toBeVisible();

  await pair.selectOption(nuisancePair);
  await expect(page.getByTestId("variant-compare").locator("img").nth(1)).toHaveAttribute(
    "src",
    /t_aec6e6e45eb47f85\/image$/,
  );
  await expect(page.getByTestId("revealed-answer")).toHaveCount(0);
  await page.getByRole("button", { name: /Reveal answers/ }).click();
  await expect(page.getByTestId("revealed-answer")).toHaveText([
    "Correct answer: NORMAL",
    "Correct answer: NORMAL",
  ]);

  // Mobile viewport: no horizontal overflow.
  await page.setViewportSize({ width: 375, height: 812 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("inspector keeps a real panel's evidence hidden until reveal", async ({ page }) => {
  await page.goto("/inspector");
  await expect(page.getByRole("heading", { name: "Evidence Inspector" })).toBeVisible();
  await page.getByLabel("Task", { exact: true }).selectOption(baseTask);
  await expect(page.getByTestId("evidence-box")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Reference answer" })).toHaveCount(0);
  await page.getByRole("button", { name: "Reveal evidence" }).click();
  await expect(page.getByRole("heading", { name: "Reference answer" })).toBeVisible();
  await expect(page.getByTestId("evidence-box").first()).toBeVisible();
  await expect(page.getByText("Raster verification", { exact: true })).toBeVisible();
  await expect(page.getByTestId("inspector-raster-status")).toBeVisible();
});

test("inspector surfaces reveal refusal without drawing evidence", async ({ page }) => {
  await page.route("**/inspector/evidence?*", (route) => route.fulfill({ status: 403 }));
  await page.goto("/inspector");
  await page.getByRole("button", { name: "Reveal evidence" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("refused evidence");
  await expect(page.getByTestId("evidence-box")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Reference answer" })).toHaveCount(0);
});

test("run reports displays and exports the local offline metrics", async ({ page, request }) => {
  test.skip(
    !process.env.PANELPROOF_REPORT_ROOT,
    "Provide a generated report for this browser check.",
  );
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Run Reports" })).toBeVisible();
  await expect(page.getByText("DEMO ONLY", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "Condition scores" })).toBeVisible();
  await page.getByRole("combobox", { name: /Condition/ }).selectOption("C1");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByRole("row", { name: /C1 · Full panel/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /C0 · Text only/ })).toHaveCount(0);
  const link = await page.getByRole("link", { name: "Download report" }).getAttribute("href");
  const response = await request.get(link!);
  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toMatchObject({ status: "demo" });
});

test("offline state is explicit when the API is unreachable", async ({ page }) => {
  await page.route("**/api/**", (r) => r.abort());
  await page.goto("/arena");
  await expect(page.getByTestId("arena-offline")).toBeVisible();
});

test("factory jobs expire explicitly and can reopen their own bundle", async ({ request }) => {
  const prefix = "reopen-" + Date.now().toString(36);
  async function generate(seed: string) {
    const started = await request.post("/api/jobs", {
      data: { seed, count: 1, difficulty: "easy" },
    });
    expect(started.ok()).toBeTruthy();
    const { job_id } = await started.json();
    await expect
      .poll(async () => (await (await request.get("/api/jobs/" + job_id)).json()).status, {
        timeout: 60_000,
      })
      .toBe("succeeded");
    return (await (await request.get("/api/jobs/" + job_id)).json()) as {
      job_id: string;
      task_ids: string[];
      reused: boolean;
    };
  }
  const first = await generate(prefix + "-first");
  const second = await generate(prefix + "-second");
  const expired = await (await request.get("/api/jobs/" + first.job_id)).json();
  expect(expired.status).toBe("expired");
  expect(expired.task_ids).toEqual([]);
  const previousTask = "/api/pp/factory/api/v1/tasks/" + first.task_ids[0];
  expect((await request.get(previousTask + "?job=" + first.job_id)).status()).toBe(410);
  expect((await request.get(previousTask + "?job=" + second.job_id)).status()).toBe(404);
  const reopened = await generate(prefix + "-first");
  expect(reopened.reused).toBe(true);
  expect(reopened.task_ids).toEqual(first.task_ids);
  expect((await request.get(previousTask + "?job=" + first.job_id)).status()).toBe(200);
});
