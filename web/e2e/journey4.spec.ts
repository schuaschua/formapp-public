import { expect, test, type Page } from "@playwright/test";
import { strings } from "../src/strings";

// Story 4.4, P2-003: journey 4 (two tabs, one edit lock) on the local stack -- the real api +
// PostgreSQL, started by this config's second `webServer` entry, signed in as the test principal,
// never against Azure (AD-18). Both tabs are the same agent (two browser contexts, standing in for
// a second window or device, AD-16): the lock is per-tab, not per-agent. FORM-222: a new proposal
// is now schema v2 (4 pages: Product, Payment, Particulars, Health & lifestyle); the shared field
// this journey fights over moved from page 1 (Needs, dropped) to page 4 (Health & lifestyle).
test.use({
  extraHTTPHeaders: { "X-Formapp-Test-Principal": "agent-a" },
});

function row(page: Page, questionText: string) {
  return page.locator(".ws-tbl__row").filter({ hasText: questionText });
}

test("journey 4: a second tab opens read-only, takes over, and the first tab loses the lock", async ({
  page: tabA,
  browser,
}) => {
  // Tab A creates the draft and holds the lock from the moment it opens (Story 4.4: the lock
  // endpoint is called on open).
  await tabA.goto("/proposals");
  await tabA
    .getByRole("button", { name: strings.proposals.newProposal })
    .click();
  await expect(
    tabA.getByRole("heading", { level: 2, name: /1 · Product/ }),
  ).toBeVisible();
  const draftUrl = tabA.url();

  await tabA.getByRole("button", { name: /Payment/ }).click();
  await expect(
    tabA.getByRole("heading", { level: 2, name: /2 · Payment/ }),
  ).toBeVisible();
  await row(tabA, "Payment method")
    .getByRole("button", { name: "Direct debit", exact: true })
    .click();
  await expect(tabA.getByRole("status")).toHaveText(/Saved/);

  // Tab B: a second window on the same draft, same agent (a second browser context, since the
  // lock identity is the per-tab X-Session-Id, not the signed-in agent, AD-16).
  const contextB = await browser.newContext({
    extraHTTPHeaders: { "X-Formapp-Test-Principal": "agent-a" },
  });
  const tabB = await contextB.newPage();
  await tabB.goto(draftUrl);
  await expect(
    tabB.getByRole("heading", { level: 2, name: /1 · Product/ }),
  ).toBeVisible();

  // Tab B is read-only, with the lock-elsewhere note and an enabled "Edit here instead".
  await expect(
    tabB.locator(".info-note").getByText(strings.workspace.lockedElsewhereNote),
  ).toBeVisible();
  await tabB.getByRole("button", { name: /Health & lifestyle/ }).click();
  const diagnosesB = row(
    tabB,
    "Have you ever been diagnosed with heart disease, stroke, cancer or diabetes?",
  );
  await expect(diagnosesB.getByRole("button", { name: "Yes" })).toBeDisabled();
  const editHereInstead = tabB.getByRole("button", {
    name: strings.workspace.editHereInstead,
  });
  await expect(editHereInstead).toBeEnabled();

  // Tab B takes over: it becomes editable, and the note clears there.
  await editHereInstead.click();
  await expect(
    tabB.locator(".info-note").getByText(strings.workspace.lockedElsewhereNote),
  ).not.toBeVisible();
  await expect(diagnosesB.getByRole("button", { name: "Yes" })).toBeEnabled();
  await diagnosesB.getByRole("button", { name: "Yes" }).click();
  await expect(tabB.getByRole("status")).toHaveText(/Saved/);

  // Tab A finds out only when it next tries to write (spec: no push channel, AD-16): its click
  // is refused with lock_not_held, the value it clicked stays on screen with a "not saved" note,
  // never "Saved ✓", and the form goes read-only with the same lock-elsewhere note. Tab A hasn't
  // been to Health & lifestyle yet, so it still has to navigate there first, same as tab B did.
  await tabA.getByRole("button", { name: /Health & lifestyle/ }).click();
  const diagnosesA = row(
    tabA,
    "Have you ever been diagnosed with heart disease, stroke, cancer or diabetes?",
  );
  await diagnosesA.getByRole("button", { name: "No" }).click();
  await expect(
    tabA.locator(".info-note").getByText(strings.workspace.lockedElsewhereNote),
  ).toBeVisible();
  await expect(tabA.getByText(strings.workspace.saved)).not.toBeVisible();
  await expect(diagnosesA.getByRole("button", { name: "No" })).toBeDisabled();

  await contextB.close();
});
