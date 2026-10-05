import { expect, test, type Page } from "@playwright/test";
import { strings } from "../src/strings";

// Story 1.10, P1-018: journey 1 (fill answers, reload, answers still there) on the local stack --
// the real api + PostgreSQL, started by this config's second `webServer` entry, bootstrapped by
// `api/scripts/e2e_bootstrap.py` -- signed in as the test principal, never against Azure (AD-18).
// FORM-222: a new proposal is now schema v2 (4 pages: Product, Payment, Particulars, Health &
// lifestyle) -- this journey exercises three of them.
test.use({
  extraHTTPHeaders: { "X-Formapp-Test-Principal": "agent-a" },
});

function row(page: Page, questionText: string) {
  return page.locator(".ws-tbl__row").filter({ hasText: questionText });
}

test("journey 1: fill answers on three pages, reload, and they are all still there", async ({
  page,
}) => {
  await page.goto("/proposals");
  await page
    .getByRole("button", { name: strings.proposals.newProposal })
    .click();
  await expect(
    page.getByRole("heading", { level: 2, name: /1 · Product/ }),
  ).toBeVisible();

  // Page 2 (Payment): a segmented pill, committed on click.
  await page.getByRole("button", { name: /Payment/ }).click();
  await expect(
    page.getByRole("heading", { level: 2, name: /2 · Payment/ }),
  ).toBeVisible();
  await row(page, "Payment method")
    .getByRole("button", { name: "Direct debit", exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText(/Saved/);

  // Page 3 (Particulars): a text field, committed on blur.
  await page.getByRole("button", { name: /Particulars/ }).click();
  await expect(
    page.getByRole("heading", { level: 2, name: /3 · Particulars/ }),
  ).toBeVisible();
  const firstName = row(page, "First name").getByRole("textbox");
  await firstName.fill("Ally");
  await firstName.blur();
  await expect(page.getByRole("status")).toHaveText(/Saved/);

  // Page 4 (Health & lifestyle): the unit-mapped number input (FORM-213: a digit-only text field,
  // not a native number spinner), committed on blur.
  await page.getByRole("button", { name: /Health & lifestyle/ }).click();
  await expect(
    page.getByRole("heading", { level: 2, name: /4 · Health & lifestyle/ }),
  ).toBeVisible();
  const height = row(page, "Height (cm)").getByRole("textbox");
  await height.fill("165");
  await height.blur();
  await expect(page.getByRole("status")).toHaveText(/Saved/);

  await page.reload();
  await expect(page.getByRole("heading", { level: 2 })).toBeVisible();

  await page.getByRole("button", { name: /Health & lifestyle/ }).click();
  await expect(row(page, "Height (cm)").getByRole("textbox")).toHaveValue(
    "165",
  );

  await page.getByRole("button", { name: /Particulars/ }).click();
  await expect(row(page, "First name").getByRole("textbox")).toHaveValue(
    "Ally",
  );

  await page.getByRole("button", { name: /Payment/ }).click();
  await expect(
    row(page, "Payment method").getByRole("button", {
      name: "Direct debit",
      exact: true,
    }),
  ).toHaveClass(/ws-seg__option--on/);
});
