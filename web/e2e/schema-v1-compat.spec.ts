import { expect, test } from "@playwright/test";

// FORM-222/224, P1-018 companion: proves an existing v1 draft still opens with its own released
// schema (5 pages, page 1 "Needs", H4's full hazardous-activities list) even once form-schema/
// v2.json is the latest version every *new* draft gets (AD-7, AD-15) -- v1.json is never edited,
// so a proposal that already pinned it keeps rendering exactly as it always did.
//
// The draft itself is seeded directly into the database by `api/scripts/e2e_bootstrap.py`'s
// `seed_v1_draft` (schema_version 1, owned by the "agent-a" test principal, C1/C13 = "Vera"/
// "Legacy" so its Drafts-list row is unique and recognisable) -- nothing reachable through the
// app can create a v1 draft any more, since `create_draft` always pins the latest version.
test.use({
  extraHTTPHeaders: { "X-Formapp-Test-Principal": "agent-a" },
});

test("an existing v1 draft still opens with 5 pages, starting at Needs", async ({
  page,
}) => {
  await page.goto("/proposals");
  await page.getByRole("link", { name: /Vera_Legacy_Proposal_001/ }).click();

  await expect(
    page.getByRole("heading", { level: 2, name: /1 · Needs/ }),
  ).toBeVisible();

  for (const title of [
    "Needs",
    "Product",
    "Payment",
    "Particulars",
    "Health & lifestyle",
  ]) {
    await expect(
      page.getByRole("button", { name: title, exact: true }),
    ).toBeVisible();
  }

  // FORM-224 restricted a *new* v2 draft's H4 to None/Other; this v1 draft keeps every option
  // v1.json always had.
  await page.getByRole("button", { name: "Health & lifestyle" }).click();
  await expect(
    page.getByRole("heading", { level: 2, name: /5 · Health & lifestyle/ }),
  ).toBeVisible();
  const hazardousRow = page
    .locator(".ws-tbl__row")
    .filter({ hasText: "Do you take part in any hazardous activities?" });
  for (const option of [
    "None",
    "Scuba diving",
    "Skydiving",
    "Motor racing",
    "Mountaineering",
    "Other",
  ]) {
    await expect(
      hazardousRow.getByRole("button", { name: option, exact: true }),
    ).toBeVisible();
  }
});
