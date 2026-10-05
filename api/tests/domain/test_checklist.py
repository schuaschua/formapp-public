"""Story 4.10 (FORM-235): the AI's short opening message (FR63, AD-9)."""

from domain.checklist import opening_message


def test_form_235_opening_message_greets_by_first_name_and_names_the_three_ways() -> None:
    assert opening_message("Alice") == (
        "Hi Alice. To fill in this proposal, you can use the microphone, ask me for help, "
        "or type the details into the form yourself."
    )


def test_form_235_opening_message_lists_no_questions() -> None:
    text = opening_message("Alice")
    assert "\n" not in text
    for label in ("Particulars", "Health", "Payment frequency", "date of birth"):
        assert label not in text
