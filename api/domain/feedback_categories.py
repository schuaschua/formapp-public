"""The closed feedback-category list (Story 7.1 setup; Story 7.2 assigns them, spine AD-20).

A fixed, non-`x-fill` vocabulary -- unlike the schema question ids, these are never sent by the web
app or the agent, only written by the nightly feedback job -- so it lives here rather than in
`form-schema/`. ``"No comment"`` is a separate, ninth stored value (never a member the model is
asked to choose from): the job assigns it to a rating with no comment, never a real classification.
"""

from typing import Final

# The eight categories the model chooses from for a rating with a comment (AD-20). An answer
# outside this list is stored as "Other".
FEEDBACK_CATEGORIES: Final[tuple[str, ...]] = (
    "Accuracy",
    "Understanding",
    "Product choice",
    "Speed",
    "Voice",
    "Ease of use",
    "Praise",
    "Other",
)

# Assigned by the job itself, never by the model, to a rating with no comment (AD-20).
NO_COMMENT_CATEGORY: Final[str] = "No comment"

# Every value `proposal_feedback.category` may hold (migration 0018's CHECK constraint mirrors
# this list as a literal, not an import -- see that migration's docstring for why).
ALL_FEEDBACK_CATEGORIES: Final[tuple[str, ...]] = (
    *FEEDBACK_CATEGORIES,
    NO_COMMENT_CATEGORY,
)
