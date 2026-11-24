import { expect, test } from "@playwright/test";

test("judge flow: generate -> view -> answer -> compare -> reveal", async ({ page }) => {
  // Overview shows the API is up.
  await page.goto("/");
  await expect(page.getByTestId("api-ready")).toBeVisible();

  // Generate (real Python worker behind the Rust API).
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
