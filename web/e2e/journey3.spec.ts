import { expect, test, type Page } from "@playwright/test";
import { strings } from "../src/strings";

// Story 4.5, P1-020: journey 3 (chat with the AI, send/stream/fill) on the local stack -- the real
// api + PostgreSQL, started by playwright.config.ts's second webServer entry, signed in as the
// test principal (AD-18). FORMAPP_TEST_MODE is on and no FOUNDRY_* env vars are set, so
// adapters.rest.app's create_app() builds a StubAgentGateway automatically, playing its default
// script (a short canned reply plus a scripted patch_draft that fills C1) -- never a real Foundry
// call.
test.use({
  extraHTTPHeaders: { "X-Formapp-Test-Principal": "agent-a" },
});

function row(page: Page, questionText: string) {
  return page.locator(".ws-tbl__row").filter({ hasText: questionText });
}

test("journey 3: chatting with the AI streams a reply and fills the draft", async ({
  page,
}) => {
  await page.goto("/proposals");
  await page
    .getByRole("button", { name: strings.proposals.newProposal })
    .click();
  await expect(
    page.getByRole("heading", { level: 2, name: /1 · Product/ }),
  ).toBeVisible();

  // The chat input is enabled: this tab holds the edit lock the moment the draft opens (Story 4.4).
  const chatInput = page.getByPlaceholder(strings.workspace.chatPlaceholder);
  await expect(chatInput).toBeEnabled();

  // Story 6.2/6.4 (FORM-230/FORM-233, AD-19): the mic renders next to Send and follows its
  // enabled state -- this real-browser build never touches Speech itself (nothing here uses it).
  const micButton = page.getByRole("button", {
    name: strings.workspace.micStartSpeaking,
  });
  await expect(micButton).toBeVisible();
  await expect(micButton).toBeEnabled();

  await chatInput.fill("Her name is Ally.");
  await chatInput.press("Enter");

  // AC10: the input clears the instant she sends, whatever the turn's own timing.
  await expect(chatInput).toHaveValue("");

  // AC5/AC9-AC12: the reply streams into a left-aligned "✦ formapp AI" bubble. The local stub
  // turn is fast (no real Foundry latency), so the transient "AI is filling in answers…" note is
  // covered by ChatPanel.test.tsx's own paused-stream test instead of asserted here.
  // Story 4.6: the opening checklist is already its own "✦ formapp AI" bubble at the top of the
  // history, so `.last()` picks the reply's, not the checklist's.
  await expect(
    page.getByText(strings.workspace.chatAiLabel).last(),
  ).toBeVisible();
  await expect(
    page.locator(".chat-bubble--ai .chat-bubble__text").last(),
  ).toContainText("Got it. I've noted that for the proposal.");

  // AC11: once the stream ends, the form is still in place (still on page 1, no navigation, no
  // blank flash) and re-fetched with the AI's write.
  await expect(
    page.getByRole("heading", { level: 2, name: /1 · Product/ }),
  ).toBeVisible();

  // AC12: the stub's scripted patch_draft actually landed -- C1, on page 4 (Particulars).
  await page.getByRole("button", { name: "Particulars" }).click();
  await expect(row(page, "First name").locator("input")).toHaveValue("Ally");

  // The lock is back with this tab: chat is usable again (the send button itself stays disabled
  // with nothing typed -- that's a separate, always-true rule, not part of this story's own AC).
  await expect(chatInput).toBeEnabled();
  await expect(micButton).toBeEnabled();
});
