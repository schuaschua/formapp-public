"""Story 7.1/FORM-237: the closed feedback-category list (spine AD-20), spelled out so a change is
noticed -- migration 0018's CHECK constraint is a frozen copy of this same list."""

from domain.feedback_categories import (
    ALL_FEEDBACK_CATEGORIES,
    FEEDBACK_CATEGORIES,
    NO_COMMENT_CATEGORY,
)


def test_form_237_feedback_categories_are_the_eight_ad_20_values() -> None:
    assert FEEDBACK_CATEGORIES == (
        "Accuracy",
        "Understanding",
        "Product choice",
        "Speed",
        "Voice",
        "Ease of use",
        "Praise",
        "Other",
    )


def test_form_237_no_comment_is_not_one_of_the_model_s_choices() -> None:
    # The job assigns "No comment" itself; the model is never offered it as an option (AD-20).
    assert NO_COMMENT_CATEGORY == "No comment"
    assert NO_COMMENT_CATEGORY not in FEEDBACK_CATEGORIES


def test_form_237_all_categories_is_the_eight_plus_no_comment() -> None:
    assert ALL_FEEDBACK_CATEGORIES == (*FEEDBACK_CATEGORIES, "No comment")
    assert len(ALL_FEEDBACK_CATEGORIES) == 9
