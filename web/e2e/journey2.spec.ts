import { expect, test, type Page } from "@playwright/test";
import { strings } from "../src/strings";

// Story 3.3/FORM-21, P1-019: journey 2 (submit with errors -> highlights and first problem page;
// fix -> declaration -> rating -> submitted list) on the local stack -- the real api + PostgreSQL,
// started by this config's second `webServer` entry, signed in as the test principal, never
// against Azure (AD-18). Mirrors EXPERIENCE.md's own "Flow 2 -- Alice submits (validation fails,
// then passes)". FORM-222: a new proposal is now schema v2 (4 pages: Product, Payment,
// Particulars, Health & lifestyle -- page 1 "Needs" is dropped, so N1-N4 no longer exist; N6/N7/N8
// moved onto Health & lifestyle).
test.use({
  extraHTTPHeaders: { "X-Formapp-Test-Principal": "agent-a" },
});

function row(page: Page, questionText: string) {
  return page.locator(".ws-tbl__row").filter({ hasText: questionText });
}

async function saved(page: Page) {
  await expect(page.getByRole("status")).toHaveText(/Saved/);
}

async function fillTextbox(page: Page, question: string, value: string) {
  const field = row(page, question).getByRole("textbox");
  await field.fill(value);
  await field.blur();
}

test("journey 2: submit with errors highlights the first problem page; fixing them opens declaration, then feedback, then lands on Submitted", async ({
  page,
}) => {
  await page.goto("/proposals");
  await page
    .getByRole("button", { name: strings.proposals.newProposal })
    .click();
  await expect(
    page.getByRole("heading", { level: 2, name: /1 · Product/ }),
  ).toBeVisible();

  // Page 1 (Product): FSH, the epic's own reference product (18-55), 20-year term. Fully answered
  // -- this journey's two deliberate problems live on Payment and Health & lifestyle instead.
  await row(page, "Selected product")
    .getByRole("combobox")
    .selectOption({ label: "FamilyShield Life & Health" });
  await saved(page);
  await row(page, "Policy term")
    .getByRole("combobox")
    .selectOption({ label: "20 yrs" });
  await saved(page);

  // Page 2 (Payment): every required field except Y1 (payment frequency) -- left blank on
  // purpose, this journey's own "page 2 has a problem".
  await page.getByRole("button", { name: /Payment/ }).click();
  await expect(
    page.getByRole("heading", { level: 2, name: /2 · Payment/ }),
  ).toBeVisible();
  await row(page, "Payment method")
    .getByRole("button", { name: "Credit card", exact: true })
    .click();
  await saved(page);

  // Page 3 (Particulars): Ally Macbeal, the epic's own reference customer -- C3 = male, so
  // Gynaecology (G1-G3/H15) never activates and needs no answer of its own.
  await page.getByRole("button", { name: /Particulars/ }).click();
  await expect(
    page.getByRole("heading", { level: 2, name: /3 · Particulars/ }),
  ).toBeVisible();
  await fillTextbox(page, "First name", "Ally");
  await fillTextbox(page, "Last name", "Macbeal");
  const dateOfBirth = row(page, "Date of birth").locator("input");
  await dateOfBirth.fill("1994-11-20");
  await dateOfBirth.blur();
  await row(page, "Sex at birth")
    .getByRole("button", { name: "Male", exact: true })
    .click();
  await row(page, "Country of origin")
    .getByRole("combobox")
    .selectOption({ label: "Malaysia" });
  await row(page, "Country of residence")
    .getByRole("combobox")
    .selectOption({ label: "Malaysia" });
  await fillTextbox(page, "National ID or passport number", "S1234567");
  await fillTextbox(page, "Email", "ally@example.test");
  await fillTextbox(page, "Mobile number", "+60123456789");
  await fillTextbox(page, "Street address", "1 Jalan Test");
  await fillTextbox(page, "Occupation", "Graphic designer");
  await row(page, "Marital status")
    .getByRole("combobox")
    .selectOption({ label: "Single" });
  await fillTextbox(page, "City", "Kuala Lumpur");
  await fillTextbox(page, "Postcode", "50450");
  await saved(page);

  // Page 4 (Health & lifestyle): every required field except H2 (weight) -- this journey's own
  // "page 4 has a problem" (H7-H14 are x-simple/x-fill:default, already "No" from create_draft).
  // N6 (tobacco) = No, so N7 never activates; N8 (pregnancy plans) only activates once C3 = female
  // (answered above as male): never active in this journey, so it needs no answer of its own.
  await page.getByRole("button", { name: /Health & lifestyle/ }).click();
  await expect(
    page.getByRole("heading", { level: 2, name: /4 · Health & lifestyle/ }),
  ).toBeVisible();
  await row(
    page,
    "Have you used tobacco or nicotine products in the last 12 months?",
  )
    .getByRole("button", { name: "No", exact: true })
    .click();
  await fillTextbox(page, "Height (cm)", "165");
  await row(page, "How many alcoholic drinks do you have per week?")
    .getByRole("combobox")
    .selectOption({ label: "None" });
  await row(page, "Do you take part in any hazardous activities?")
    .getByRole("button", { name: "None", exact: true })
    .click();
  await row(
    page,
    "Has a parent or sibling been diagnosed before age 60 with heart disease, stroke, cancer or diabetes?",
  )
    .getByRole("button", { name: "None", exact: true })
    .click();
  await row(
    page,
    "Have you ever been diagnosed with heart disease, stroke, cancer or diabetes?",
  )
    .getByRole("button", { name: "No", exact: true })
    .click();
  await saved(page);

  // First Submit: Y1 and H2 are both still unanswered. Validation fails on both pages; the form
  // jumps to page 2, the first (lowest-numbered) problem page, with no modal (EXPERIENCE.md
  // Flow 2, steps 1-2).
  await page
    .getByRole("button", { name: strings.workspace.submitProposal })
    .click();
  await expect(
    page.getByRole("heading", { level: 2, name: /2 · Payment/ }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Payment/ })).toHaveClass(
    /page-menu__item--problem/,
  );
  await expect(
    page.getByRole("button", { name: /Health & lifestyle/ }),
  ).toHaveClass(/page-menu__item--problem/);
  await expect(page.getByText("Answer required")).toBeVisible();
  await expect(page.getByRole("dialog")).not.toBeVisible();

  // Fix page 2's problem: its highlight and the menu's amber box both clear at once.
  await row(page, "Payment frequency")
    .getByRole("button", { name: "Monthly", exact: true })
    .click();
  await expect(page.getByText("Answer required")).not.toBeVisible();
  await expect(page.getByRole("button", { name: /Payment/ })).not.toHaveClass(
    /page-menu__item--problem/,
  );

  // Fix page 4's problem the same way.
  await page.getByRole("button", { name: /Health & lifestyle/ }).click();
  await expect(page.getByText("Answer required")).toBeVisible();
  await fillTextbox(page, "Weight (kg)", "70");
  await expect(page.getByText("Answer required")).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: /Health & lifestyle/ }),
  ).not.toHaveClass(/page-menu__item--problem/);

  // Second Submit: validation passes now. The declaration modal opens (EXPERIENCE.md Flow 2, step
  // 4).
  await page
    .getByRole("button", { name: strings.workspace.submitProposal })
    .click();
  const declaration = page.getByRole("dialog", {
    name: strings.workspace.declarationTitle,
  });
  await expect(declaration).toBeVisible();
  await expect(declaration).toContainText(strings.workspace.declarationText);
  await declaration
    .getByRole("button", { name: strings.workspace.iAgree })
    .click();

  // The feedback modal replaces it, never stacked (step 5): "Submit proposal" stays disabled
  // until she picks a rating.
  const feedback = page.getByRole("dialog", {
    name: strings.workspace.feedbackTitle,
  });
  await expect(feedback).toBeVisible();
  await expect(declaration).not.toBeVisible();
  const feedbackSubmit = feedback.getByRole("button", {
    name: strings.workspace.submitProposal,
  });
  await expect(feedbackSubmit).toBeDisabled();
  await feedback
    .getByRole("radio", { name: strings.workspace.ratingStarLabel(4) })
    .click();
  await expect(feedbackSubmit).toBeEnabled();
  await feedback
    .getByLabel(strings.workspace.commentLabel)
    .fill(
      "It set 'ever been pregnant' to No by default, but it saved me a lot of typing.",
    );

  // Climax (step 6): the app moves to My proposals › Submitted, Ally Macbeal on top, with the
  // success toast.
  await feedbackSubmit.click();
  await expect(page).toHaveURL(/\/proposals\/submitted$/);
  await expect(
    page.getByText(strings.workspace.submitSuccessToast),
  ).toBeVisible();
  const rows = page.locator(".proposals-row");
  await expect(rows.first()).toContainText("Ally");
  await expect(rows.first()).toContainText("Macbeal");
  await expect(rows.first()).toContainText(strings.proposals.statusSubmitted);
});
