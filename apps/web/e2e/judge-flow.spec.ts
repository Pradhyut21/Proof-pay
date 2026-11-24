import { expect, test } from "@playwright/test";

test("judge flow: generate -> view -> answer -> compare -> reveal", async ({ page }) => {
  // Overview shows the API is up.
  await page.goto("/");
  await expect(page.getByTestId("api-ready")).toBeVisible();

  // Generate with the real Python worker and serve the result from Axum.
  await page.goto("/factory");
  await page.getByLabel("Seed").fill("e2e-judge");
  await page.getByLabel(/Number of panels/).fill("2");
  await page.getByRole("button", { name: "Generate" }).click();
  await expect(page.getByTestId("run-status")).toContainText("Succeeded", { timeout: 90_000 });
  // Each base scene yields several tasks; the page shows at most four.
  await expect(page.locator("figure").first()).toBeVisible();
  expect(await page.locator("figure").count()).toBeLessThanOrEqual(4);

  // Invalid answer is rejected client-side with an accessible message.
  await page.getByRole("button", { name: "Submit answer" }).first().click();
  await expect(page.getByRole("alert").first()).toBeVisible();

  // Counterfactual pair compare + a human attempt + reveal.
  await page.goto("/arena");
  await expect(page.getByTestId("variant-compare").locator("figure")).toHaveCount(2);
  await page.getByRole("radio").first().check();
  await page.getByRole("button", { name: "Submit answer" }).first().click();
  await expect(page.locator('[data-testid^="outcome-"]').first()).toBeVisible();
  await expect(page.getByText(/DEMO ONLY/).first()).toBeVisible();
  await page.getByRole("button", { name: /Reveal answers/ }).click();
  await expect(page.getByTestId("revealed-answer")).toHaveCount(2);
  await expect(page.getByTestId("evidence-box").first()).toBeVisible();

  // Mobile viewport: no horizontal overflow.
  await page.setViewportSize({ width: 375, height: 812 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
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
