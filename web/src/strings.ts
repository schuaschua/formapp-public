// Every piece of user-facing text, worded as in EXPERIENCE.md Voice and Tone (coding-style.md rule 18):
// plain and short, no exclamation marks, no emoji.
export const strings = {
  appName: "formapp",
  logoInitial: "f",
  skipToMain: "Skip to main content",
  /** The browser tab title for a page. */
  documentTitle: (page: string) => `${page} - formapp`,
  /** FORM-218: the customer number shown on the Submitted list and the submitted read-only view,
   * e.g. "Customer CUS-10023". */
  customerNumberLabel: (number: string) => `Customer ${number}`,
  welcome: {
    title: "formapp",
    documentTitle: "formapp",
    tagline:
      "Tell the AI about your customer. It fills in the proposal for you to check.",
    signIn: "Sign in with Microsoft",
    // Story 1.6: the real lifestyle photo is carried in deferred-work.md; this labels its slot.
    photoPlaceholder: "Photo placeholder",
    // Decoration on the photo (hidden from screen readers), built from the synthetic seed persona.
    chipProposalLabel: "Proposal",
    chipProposalName: "Ally Macbeal",
    chipFilledByChat: "\u2726 filled by chat",
    chipProduct: "FamilyShield Life & Health",
    chipChat:
      "Ally Macbeal, born 20th November 1994, just married, planning a baby\u2026",
  },
  account: {
    /** The avatar button's name: her first name first, so it matches what is on screen. */
    buttonLabel: (firstName: string) => `${firstName}, account menu`,
    menuLabel: "Account",
    signOut: "Sign out",
  },
  proposals: {
    title: "My proposals",
    drafts: "Drafts",
    submitted: "Submitted",
    newProposal: "+ New proposal",
    creating: "Creating your new proposal.",
    emptyDrafts: "No drafts yet",
    emptySubmitted: "Nothing submitted yet.",
    createdPrefix: "Created",
    submittedPrefix: "Submitted",
    statusDraft: "Draft",
    statusSubmitted: "Submitted",
    loadError: "Something went wrong loading your proposals.",
    // Story FORM-227: the per-row delete action's own accessible name.
    deleteRowLabel: (name: string) => `Delete ${name}`,
  },
  workspace: {
    /** The document title while the draft hasn't loaded yet, before her breadcrumb replaces it. */
    title: "Proposal",
    /** Hardcoded from mockups/key-workspace.html (spec assumption "Page titles"): the schema has
     * no page title. Keyed by schema version (FORM-222: v2 drops page 1 "Needs" and renumbers
     * the rest), so a v1 draft and a v2 draft each get their own page's title. */
    pagesByVersion: {
      1: {
        1: "Needs",
        2: "Product",
        3: "Payment",
        4: "Particulars",
        5: "Health & lifestyle",
      },
      2: {
        1: "Product",
        2: "Payment",
        3: "Particulars",
        4: "Health & lifestyle",
      },
    } as Record<number, Record<number, string>>,
    pageHeading: (page: number, name: string) => `${page} · ${name}`,
    pagesLabel: "Pages",
    collapseMenu: "Collapse menu",
    expandMenu: "Expand menu",
    pagesDone: (done: number, total: number) =>
      `${done} of ${total} pages done`,
    questionColumn: "Question",
    answerColumn: "Answer",
    gynaecology: "Gynaecology",
    chooseProductFirst: "Choose a product first.",
    chatPlaceholder: "Type an answer or ask the AI…",
    // Story 4.5: the chat panel (DESIGN.md "Chat panel"/"Chat input"/"Send button",
    // EXPERIENCE.md "AI replying"/"Failure/cutoff").
    chatAiLabel: "✦ formapp AI",
    chatLocklessPlaceholder: "Chat is available in the window that is editing",
    chatSend: "Send",
    // Story 6.2 (FORM-230): the mic button (DESIGN.md "components.mic-button", EXPERIENCE.md
    // "Mic"/"Listening"/"Voice unavailable", UX-DR44/UX-DR45) -- worded exactly as the UX gives it.
    // Story 6.4/6.5 (FORM-233/FORM-234, owner change 2026-09-28): tap-to-toggle superseded
    // press-and-hold, so the idle/listening accessible names changed too (EXPERIENCE.md "Mic
    // button (accessible name)").
    micStartSpeaking: "Start speaking",
    micStopAndSend: "Stop and send",
    micListening: "Listening",
    micBlockedMessage:
      "Microphone blocked. Allow it in your browser, or type instead.",
    micUnavailableMessage:
      "Voice isn't available right now. Please type instead.",
    micNoSpeechMessage: "Didn't catch that. Tap the mic and try again.",
    aiReplyingNote: "AI is filling in answers…",
    chatFailureMessage:
      "The AI couldn't finish. Answers so far are saved. Please try again.",
    chatHistoryLoadError: "Something went wrong loading the chat.",
    // Story 4.8: the throttled Send button's "Wait Ns" pill (EXPERIENCE.md "Chat input + send",
    // DESIGN.md "send-button-wait").
    chatWait: (seconds: number) => `Wait ${seconds}s`,
    loadError: "Something went wrong loading this proposal.",
    saving: "Saving…",
    saved: "Saved",
    saveFailedMessage: "Couldn't save. Retrying...",
    connectionLostMessage:
      "Connection lost. Your answers will save when you're back online.",
    retry: "Retry",
    // Story 4.4: the edit lock (EXPERIENCE.md "Lock elsewhere", DESIGN.md "Other-window note").
    lockedElsewhereNote: "This proposal is open for editing in another window",
    editHereInstead: "Edit here instead",
    editHereInsteadDisabledReason: "The AI is filling in answers.",
    submitProposal: "Submit proposal",
    /** The page-menu problem badge's accessible name suffix (mirrors the "done" pattern). */
    answersNeeded: "Answers needed",
    submitOfflineReason: "Connection lost.",
    submitReadOnlyReason: "Read-only in this window.",
    submitUnsavedReason: "Your last answer hasn't saved yet.",
    submitCheckingReason: "Checking your answers…",
    submitCheckFailedMessage: "Couldn't check the proposal. Try again.",
    /** FORM-213: the amber problem message under a number field once something non-numeric has
     * reached it (a paste, autofill) -- letters can't be typed there in the first place. */
    numberFieldInvalidMessage: "Enter numbers only.",
    // Story 3.2: the read-only workspace's submitted strip (DESIGN.md "Submitted strip").
    submittedOn: (date: string) => `Submitted on ${date}`,
    // Story 3.3/FORM-21: the declaration modal, feedback modal and success toast
    // (EXPERIENCE.md "Submit modals", DESIGN.md Components "Declaration box"/"Rating tiles"/
    // "Toast (success)").
    cancel: "Cancel",
    declarationTitle: "Declaration",
    declarationText:
      "I confirm I have reviewed every answer with the customer and it is true and complete.",
    iAgree: "I agree",
    feedbackTitle: "How helpful was the AI on this proposal?",
    ratingLabel: "Rating (required)",
    ratingStarLabel: (rating: number) =>
      `${rating} star${rating === 1 ? "" : "s"}`,
    commentLabel: "Comment (optional)",
    feedbackHint: "A rating is required to submit.",
    submitInProgressReason: "Submitting…",
    submitSuccessToast: "Proposal submitted. Thank you for your feedback.",
    submitFailedMessage: "Couldn't submit the proposal. Try again.",
    // Story FORM-227: the workspace's own delete-draft button (the shared confirmation modal's
    // strings live in deleteDraftModal below, one set for both call sites).
    deleteDraft: "Delete draft",
  },
  // Story FORM-227: the shared delete-draft confirmation modal, opened from a Drafts row and from
  // the workspace alike (one component, one deleteProposal(id) client call).
  deleteDraftModal: {
    title: (name: string) => `Delete ${name}?`,
    body: "This can't be undone. The draft and everything in it will be deleted for good.",
    cancel: "Cancel",
    confirm: "Delete",
    deleting: "Deleting…",
    toast: "Draft deleted.",
    failedMessage: "Couldn't delete the draft. Try again.",
    // FORM-232: the two refusals Alice can do something about (AD-16's lock, an AI turn).
    lockedMessage:
      "This draft is still open for editing in another window. Try again in a minute.",
    aiBusyMessage:
      "The AI is still working on this draft. Try again when it finishes.",
  },
  priceSummary: {
    // epic-2-context.md "Price summary on pages 2 and 3": read-only, built only from `quote`.
    placeholder: "The price shows once a product and date of birth are set.",
    line: (name: string, monthly: string, yearly: string) =>
      `${name}: ${monthly} monthly, ${yearly} yearly`,
    total: (monthly: string, yearly: string) =>
      `Total: ${monthly} monthly, ${yearly} yearly (paying yearly saves 5%)`,
  },
} as const;
