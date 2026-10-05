"""The AI's opening message (Story 4.6, amended by Story 4.10 / FORM-235; spine AD-9).

CAP-4: the first "formapp AI" message on every draft, built when ``GET /api/proposals/:id/chat``
is called -- never a model call, no throttle slot, no lock, and never written to the Foundry
conversation (AD-9). Owner change 2026-09-28: a short welcome naming the three ways to fill the
proposal, instead of 4.6's list of every question (the agent must not be bombarded).
"""

_OPENING = (
    "Hi {first_name}. To fill in this proposal, you can use the microphone, ask me for help, "
    "or type the details into the form yourself."
)


def opening_message(first_name: str) -> str:
    """The opening welcome for the signed-in insurance agent (FR63). Pure and side-effect-free."""
    return _OPENING.format(first_name=first_name)
