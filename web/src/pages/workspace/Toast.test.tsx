import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Toast } from "./Toast";

describe("3.3 success toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the message as a status region", () => {
    render(<Toast message="Proposal submitted." onDismiss={vi.fn()} />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Proposal submitted.");
  });

  it("dismisses itself after a few seconds", () => {
    const onDismiss = vi.fn();
    render(<Toast message="Proposal submitted." onDismiss={onDismiss} />);

    vi.advanceTimersByTime(4999);
    expect(onDismiss).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("clears its timer on unmount", () => {
    const onDismiss = vi.fn();
    const { unmount } = render(
      <Toast message="Proposal submitted." onDismiss={onDismiss} />,
    );

    unmount();
    vi.advanceTimersByTime(10000);

    expect(onDismiss).not.toHaveBeenCalled();
  });
});
