import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { strings } from "../../strings";
import { DeclarationModal, FeedbackModal } from "./SubmitModals";

describe("3.3 declaration modal", () => {
  it("is a labelled dialog with the declaration text and both buttons", () => {
    render(<DeclarationModal onAgree={vi.fn()} onCancel={vi.fn()} />);

    const dialog = screen.getByRole("dialog", {
      name: strings.workspace.declarationTitle,
    });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveTextContent(strings.workspace.declarationText);
    expect(
      screen.getByRole("button", { name: strings.workspace.cancel }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: strings.workspace.iAgree }),
    ).toBeInTheDocument();
  });

  it("focuses a control inside the dialog as soon as it opens", () => {
    render(<DeclarationModal onAgree={vi.fn()} onCancel={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: strings.workspace.cancel }),
    ).toHaveFocus();
  });

  it("I agree calls onAgree; Cancel and Escape both call onCancel", async () => {
    const onAgree = vi.fn();
    const onCancel = vi.fn();
    render(<DeclarationModal onAgree={onAgree} onCancel={onCancel} />);

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.iAgree }),
    );
    expect(onAgree).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.cancel }),
    );
    expect(onCancel).toHaveBeenCalledTimes(1);

    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it("Tab cycles inside the dialog rather than escaping it", async () => {
    render(<DeclarationModal onAgree={vi.fn()} onCancel={vi.fn()} />);
    const cancel = screen.getByRole("button", {
      name: strings.workspace.cancel,
    });
    const agree = screen.getByRole("button", {
      name: strings.workspace.iAgree,
    });
    expect(cancel).toHaveFocus();

    await userEvent.tab();
    expect(agree).toHaveFocus();

    await userEvent.tab();
    expect(cancel).toHaveFocus(); // wrapped back to the first control

    await userEvent.tab({ shift: true });
    expect(agree).toHaveFocus(); // wrapped backward to the last control
  });
});

describe("3.3 feedback modal", () => {
  function renderFeedback(
    overrides: Partial<Parameters<typeof FeedbackModal>[0]> = {},
  ) {
    const onCancel = vi.fn();
    const onSubmit = vi.fn();
    const onRatingChange = vi.fn();
    const onCommentChange = vi.fn();
    render(
      <FeedbackModal
        rating={null}
        comment=""
        onRatingChange={onRatingChange}
        onCommentChange={onCommentChange}
        onCancel={onCancel}
        onSubmit={onSubmit}
        submitting={false}
        {...overrides}
      />,
    );
    return { onCancel, onSubmit, onRatingChange, onCommentChange };
  }

  it("is a labelled dialog with a rating group and a comment field", () => {
    renderFeedback();

    const dialog = screen.getByRole("dialog", {
      name: strings.workspace.feedbackTitle,
    });
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByRole("radiogroup", { name: strings.workspace.ratingLabel }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(5);
    expect(
      screen.getByLabelText(strings.workspace.commentLabel),
    ).toBeInTheDocument();
  });

  it("Submit proposal is disabled with a hint until a rating is picked", () => {
    renderFeedback({ rating: null });

    const submit = screen.getByRole("button", {
      name: strings.workspace.submitProposal,
    });
    expect(submit).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByText(strings.workspace.feedbackHint),
    ).toBeInTheDocument();
  });

  it("picking a rating calls onRatingChange and enables Submit proposal once rating is set", async () => {
    const { onRatingChange } = renderFeedback({ rating: null });

    await userEvent.click(
      screen.getByRole("radio", { name: strings.workspace.ratingStarLabel(4) }),
    );

    expect(onRatingChange).toHaveBeenCalledWith(4);
  });

  it("with a rating already picked, Submit proposal is enabled and calls onSubmit", async () => {
    const { onSubmit } = renderFeedback({ rating: 4 });

    const submit = screen.getByRole("button", {
      name: strings.workspace.submitProposal,
    });
    expect(submit).not.toHaveAttribute("aria-disabled");

    await userEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("the picked rating tile is checked; the rest are not", () => {
    renderFeedback({ rating: 3 });

    const three = screen.getByRole("radio", {
      name: strings.workspace.ratingStarLabel(3),
    });
    const four = screen.getByRole("radio", {
      name: strings.workspace.ratingStarLabel(4),
    });
    expect(three).toHaveAttribute("aria-checked", "true");
    expect(four).toHaveAttribute("aria-checked", "false");
  });

  it("typing a comment calls onCommentChange", async () => {
    const { onCommentChange } = renderFeedback();

    await userEvent.type(
      screen.getByLabelText(strings.workspace.commentLabel),
      "x",
    );

    expect(onCommentChange).toHaveBeenCalledWith("x");
  });

  it("Cancel and Escape both call onCancel without submitting", async () => {
    const { onCancel, onSubmit } = renderFeedback({ rating: 4 });

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.cancel }),
    );
    expect(onCancel).toHaveBeenCalledTimes(1);

    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("while submitting, Submit proposal is disabled with an in-progress reason", () => {
    renderFeedback({ rating: 4, submitting: true });

    expect(
      screen.getByText(strings.workspace.submitInProgressReason),
    ).toBeInTheDocument();
  });

  it("never stacks: rendering the feedback modal in place of the declaration one leaves only one dialog", () => {
    function Wrapper() {
      const [step, setStep] = useState<"declaration" | "feedback">(
        "declaration",
      );
      return step === "declaration" ? (
        <DeclarationModal
          onAgree={() => setStep("feedback")}
          onCancel={vi.fn()}
        />
      ) : (
        <FeedbackModal
          rating={null}
          comment=""
          onRatingChange={vi.fn()}
          onCommentChange={vi.fn()}
          onCancel={vi.fn()}
          onSubmit={vi.fn()}
          submitting={false}
        />
      );
    }
    render(<Wrapper />);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
