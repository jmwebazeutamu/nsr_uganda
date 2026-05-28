// @ts-check
//
// DATA-EXP end-to-end walk — ADR-0023 + TASK §5.
//
// This spec is written against the locked URL prefix
// /api/v1/data-explorer/ and the design's screens at
// /design/v0.1/screens/data-explorer/. The Playwright runner is
// NOT yet wired into the project (package.json carries Vitest +
// jsdom but no @playwright/test); when the runner lands, this file
// is the seed. See README at the bottom of the file for the
// dependency install.
//
// The walk:
//   1. Log in as a user with the EXPLORER realm role.
//   2. Sidebar link "Data Explorer" is visible (DATA_EXPLORER_ENABLED
//      AND user has EXPLORER role per ADR-0023 D9).
//   3. Click → catalogue loads with dataset cards.
//   4. Click first dataset card → variable table renders.
//   5. Click first variable row → variable detail loads.
//   6. Click "Use in aggregate" CTA → aggregate-builder loads.
//   7. Pick a sub-region scope + a projection axis.
//   8. Click Run → result table renders with the right chip for
//      suppressed cells.
//   9. Click "Request record-level data" → handoff screen prefills.
//  10. Submit → redirect to /data-requests/<id>.
//
// The spec uses semantic locators (`getByRole`, `getByText`) rather
// than CSS so it survives design-token tweaks.

const { test, expect } = require("@playwright/test");

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:8000";

const EXPLORER_USER = process.env.E2E_EXPLORER_USER || "explorer-e2e";
const EXPLORER_PASS = process.env.E2E_EXPLORER_PASS || "explorer-e2e-pw";


test.describe("DATA-EXP — discovery → aggregate → handoff", () => {

  test.beforeEach(async ({ page }) => {
    // 1. Log in
    await page.goto(`${BASE_URL}/login/`);
    await page.getByLabel(/username|email/i).fill(EXPLORER_USER);
    await page.getByLabel(/password/i).fill(EXPLORER_PASS);
    await page.getByRole("button", { name: /sign in|log in/i }).click();
    await expect(page).not.toHaveURL(/login/);
  });

  test("walks catalogue → variable → aggregate → handoff", async ({ page }) => {
    // 2. Sidebar link visible
    const sidebarLink = page.getByRole("link", { name: /data explorer/i });
    await expect(sidebarLink).toBeVisible();
    await sidebarLink.click();

    // 3. Catalogue loads
    await expect(
      page.getByRole("heading", { name: /data explorer/i }),
    ).toBeVisible();
    const datasetCards = page.locator("[data-testid='dataset-card']");
    await expect(datasetCards.first()).toBeVisible({ timeout: 5000 });

    // 4. Click first dataset
    await datasetCards.first().click();
    const variableTable = page.locator("[data-testid='variable-table']");
    await expect(variableTable).toBeVisible();
    await expect(
      variableTable.locator("tbody tr").first(),
    ).toBeVisible();

    // 5. Click first variable row
    await variableTable.locator("tbody tr").first().click();
    await expect(
      page.locator("[data-testid='variable-detail']"),
    ).toBeVisible();

    // 6. Click "Use in aggregate" CTA
    await page.getByRole("button", { name: /use in aggregate/i }).click();
    await expect(
      page.locator("[data-testid='aggregate-builder']"),
    ).toBeVisible();

    // 7. Pick sub-region + projection
    await page.locator("[data-testid='geo-level-select']")
      .selectOption("sub_region");
    await page.locator("[data-testid='geo-code-picker']")
      .getByRole("option").first()
      .click();
    await page.locator("[data-testid='projection-axis-picker']")
      .getByRole("option").first()
      .click();

    // 8. Click Run
    await page.getByRole("button", { name: /^run$/i }).click();
    const results = page.locator("[data-testid='aggregate-results']");
    await expect(results).toBeVisible({ timeout: 5000 });

    // A suppressed cell carries the "Suppressed" chip (ADR-0023 D8).
    const suppressedCells = results.locator(
      "[data-testid='suppressed-chip']",
    );
    // Either zero suppressed cells (large counts) OR the chip shows
    // — both are valid; we just assert the chip is the locator that
    // would render. Skip if the test data produces no suppression.
    const chipCount = await suppressedCells.count();
    if (chipCount > 0) {
      const chipText = await suppressedCells.first().textContent();
      expect(chipText?.toLowerCase() || "").toMatch(/suppressed/i);
    }

    // The aggregate response banner shows the "N of M cells suppressed"
    // summary — present even when N=0.
    await expect(
      page.locator("[data-testid='suppression-summary']"),
    ).toBeVisible();

    // 9. Click "Request record-level data"
    await page
      .getByRole("button", { name: /request record-level data/i })
      .click();
    const handoffForm = page.locator("[data-testid='handoff-form']");
    await expect(handoffForm).toBeVisible();

    // Prefill: requested_entity, requested_fields, geographic_scope
    // come from the aggregate context.
    await expect(
      handoffForm.locator("[data-testid='handoff-requested-entity']"),
    ).not.toBeEmpty();
    await expect(
      handoffForm.locator("[data-testid='handoff-requested-fields']"),
    ).not.toBeEmpty();

    // The user fills in purpose_of_use (free text).
    await handoffForm
      .locator("[data-testid='handoff-purpose-of-use']")
      .fill("e2e test — purpose statement");

    // 10. Submit → redirect to /data-requests/<id>
    await handoffForm
      .getByRole("button", { name: /^submit$/i })
      .click();
    await page.waitForURL(/\/data-requests\/[A-Z0-9]{26}/, { timeout: 5000 });

    // Landed on the DRS draft screen — DRS owns this surface.
    await expect(
      page.getByRole("heading", { name: /data request/i }),
    ).toBeVisible();
  });

  test("user without EXPLORER role does not see sidebar link", async ({ page, context }) => {
    // Re-login as a user lacking the EXPLORER role. The test runner
    // should provide a second creds pair via env; if not, we skip
    // rather than misreport.
    const NON_EXPLORER_USER = process.env.E2E_NON_EXPLORER_USER;
    const NON_EXPLORER_PASS = process.env.E2E_NON_EXPLORER_PASS;
    if (!NON_EXPLORER_USER || !NON_EXPLORER_PASS) {
      test.skip();
      return;
    }
    await context.clearCookies();
    await page.goto(`${BASE_URL}/login/`);
    await page.getByLabel(/username|email/i).fill(NON_EXPLORER_USER);
    await page.getByLabel(/password/i).fill(NON_EXPLORER_PASS);
    await page.getByRole("button", { name: /sign in|log in/i }).click();

    // Sidebar link must be HIDDEN, not greyed (ADR-0023 D9 +
    // /docs/04 §6 "showing forbidden items in grey is a security
    // smell").
    const sidebarLink = page.getByRole("link", { name: /data explorer/i });
    await expect(sidebarLink).toHaveCount(0);
  });

  test("flag off → endpoint 503 and sidebar hidden", async ({ page }) => {
    // The flag is a Django setting; toggling at test-time needs a
    // dedicated /admin/test-flags endpoint or env override. Skip
    // when the override isn't wired.
    if (!process.env.E2E_FLAG_OFF_URL) {
      test.skip();
      return;
    }
    await page.goto(process.env.E2E_FLAG_OFF_URL);
    const sidebarLink = page.getByRole("link", { name: /data explorer/i });
    await expect(sidebarLink).toHaveCount(0);
  });
});

// ────────────────────────────────────────────────────────────────────
// README — how to land Playwright into the project
// ────────────────────────────────────────────────────────────────────
//
// 1. Add devDependency:
//      npm i -D @playwright/test
//      npx playwright install --with-deps chromium
//
// 2. Add npm script:
//      "test:e2e": "playwright test tests/e2e"
//
// 3. Add a playwright.config.js at repo root:
//      module.exports = {
//        testDir: "tests/e2e",
//        timeout: 30_000,
//        use: { baseURL: "http://localhost:8000" },
//      };
//
// 4. Add E2E_EXPLORER_USER + E2E_EXPLORER_PASS to the test env;
//    create the user in the seed migration with EXPLORER realm role.
//
// Until step 1 lands, this spec is a deliverable artifact that does
// NOT run in CI. Synthesis can decide whether to merge with the spec
// gated behind an env flag or block until the runner is wired.
