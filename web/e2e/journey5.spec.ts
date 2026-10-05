import { expect, test } from "@playwright/test";
import { strings } from "../src/strings";

// Story FORM-227, P1-0xx: journey 5 (delete a draft from its Drafts row) on the local stack -- the
// real api + PostgreSQL, started by this config's second `webServer` entry, signed in as the test
// principal, never against Azure (AD-18). FORM-222: a new proposal is now schema v2 (4 pages,
// starting with Product, not Needs) -- this journey only checks the very first page loaded.
// Other journeys' drafts share the e2e database, so this journey finds its own row by id.
test.use({
  extraHTTPHeaders: { "X-Formapp-Test-Principal": "agent-a" },
});

test("journey 5: delete a draft from the Drafts row", async ({ page }) => {
  await page.goto("/proposals");
  await page
    .getByRole("button", { name: strings.proposals.newProposal })
    .click();
  await expect(
    page.getByRole("heading", { level: 2, name: /1 · Product/ }),
  ).toBeVisible();

  const draftPath = new URL(page.url()).pathname;

  // Back to Drafts in-app (same tab session): a full reload would start a new session, and the
  // workspace's own live lock from the old one would then block the delete (AD-16).
  await page.getByRole("banner").getByRole("link", { name: "formapp" }).click();
  const row = page.locator(".proposals-row", {
    has: page.locator(`a[href="${draftPath}"]`),
  });
  await expect(row).toHaveCount(1);
  const name = (await row.locator(".proposals-row__name").textContent()) ?? "";

  await row
    .getByRole("button", { name: strings.proposals.deleteRowLabel(name) })
    .click();
  const dialog = page.getByRole("dialog", {
    name: strings.deleteDraftModal.title(name),
  });
  await expect(dialog).toBeVisible();
  await dialog
    .getByRole("button", { name: strings.deleteDraftModal.confirm })
    .click();

  // The toast shows and the row is gone from the list at once (spec Acceptance Criteria).
  await expect(page.getByText(strings.deleteDraftModal.toast)).toBeVisible();
  await expect(row).toHaveCount(0);

  // Still gone after a reload: a hard delete, not just removed from this render (FR46-style
  // durability, mirrored from journey 1's own reload check).
  await page.reload();
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  await expect(row).toHaveCount(0);
});
