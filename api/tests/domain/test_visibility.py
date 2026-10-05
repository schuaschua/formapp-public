"""Story 1.7: the active (show-if) set and the inactive answers to remove (FR1, AD-15, AD-8)."""

import pytest

from domain.schema import freeze, load_schema, questions
from domain.visibility import active_questions, inactive_answer_ids, required_questions

SCHEMA = load_schema(1)
ALL_ROWS = frozenset(questions(SCHEMA)) - {"D1"}
HIDDEN_WITHOUT_ANSWERS = {"N4", "N7", "N8", "G1", "G2", "G3", "H15"}
BASE = ALL_ROWS - HIDDEN_WITHOUT_ANSWERS


def test_story_1_7_no_answers_leaves_out_every_show_if_question_and_d1() -> None:
    active = active_questions(SCHEMA, {})

    assert active == BASE
    assert len(active) == 40
    assert not active & (HIDDEN_WITHOUT_ANSWERS | {"D1"})


@pytest.mark.parametrize(
    ("answers", "added"),
    [
        ({"N3": "Yes"}, {"N4"}),
        ({"N6": "Yes"}, {"N7"}),
        ({"C3": "female"}, {"N8", "G1", "H15"}),
        ({"C3": "female", "G1": "Yes"}, {"N8", "G1", "H15", "G2", "G3"}),
        (
            {"N3": "Yes", "N6": "Yes", "C3": "female", "G1": "Yes"},
            HIDDEN_WITHOUT_ANSWERS,
        ),
    ],
)
def test_story_1_7_show_if_answers_add_their_questions(
    answers: dict[str, object], added: set[str]
) -> None:
    assert active_questions(SCHEMA, answers) == BASE | added


@pytest.mark.parametrize(
    "answers",
    [
        {"N3": "No"},
        {"N6": "No"},
        {"C3": "male"},
        {"N3": "yes"},
        {"N3": None},
        {"C3": "Female"},
    ],
)
def test_story_1_7_other_answers_add_nothing(answers: dict[str, object]) -> None:
    assert active_questions(SCHEMA, answers) == BASE


def test_story_1_7_a_stale_answer_to_an_inactive_question_activates_nothing() -> None:
    answers = {"C3": "male", "G1": "Yes", "G2": ["live_birth"], "G3": "2019"}

    active = active_questions(SCHEMA, answers)

    assert not active & {"G1", "G2", "G3"}
    assert inactive_answer_ids(SCHEMA, answers) == {"G1", "G2", "G3"}


def test_story_1_7_answer_order_does_not_matter() -> None:
    # G1 = Yes is listed before the C3 = female that activates it.
    assert active_questions(SCHEMA, {"G1": "Yes", "C3": "female"}) == BASE | {
        "N8",
        "G1",
        "H15",
        "G2",
        "G3",
    }


def test_story_1_7_inactive_answers_are_those_to_remove() -> None:
    answers = {"N3": "No", "N4": 3, "N6": "Yes", "N7": "5 a day", "C1": "Ally"}

    assert inactive_answer_ids(SCHEMA, answers) == {"N4"}
    assert inactive_answer_ids(SCHEMA, {"N3": "Yes", "N4": 3}) == frozenset()


def test_story_1_7_d1_is_never_active_and_never_removed() -> None:
    answers = {"D1": True, "C3": "female", "G1": "Yes", "N3": "Yes", "N6": "Yes"}

    assert "D1" not in active_questions(SCHEMA, answers)
    assert "D1" not in inactive_answer_ids(SCHEMA, answers)
    assert inactive_answer_ids(SCHEMA, {"D1": True}) == frozenset()


def test_story_1_7_ids_that_are_not_questions_are_not_reported_inactive() -> None:
    # Unknown ids are an unknown_field matter for validation (Story 1.10), not removal.
    assert inactive_answer_ids(SCHEMA, {"Z9": "Yes"}) == frozenset()


# Story 3.1: required_questions -- validate_proposal's "is this active-and-unanswered question
# required" lookup (spec Design Notes).


def test_story_3_1_required_questions_with_no_answers_is_the_top_level_required_set() -> (
    None
):
    ids = required_questions(SCHEMA, {})

    assert ids == frozenset(SCHEMA["required"])
    # The design notes' own check against the released schema: every always-active question is
    # required except these three.
    assert BASE - ids == {"C12", "N5", "P2"}


def test_story_3_1_required_questions_adds_a_fired_rules_then_required_once_active() -> (
    None
):
    assert required_questions(SCHEMA, {"N3": "Yes"}) == frozenset(
        SCHEMA["required"]
    ) | {"N4"}
    assert required_questions(SCHEMA, {"C3": "female", "G1": "Yes"}) == frozenset(
        SCHEMA["required"]
    ) | {"N8", "G1", "H15", "G2", "G3"}


def test_story_3_1_required_questions_excludes_an_inactive_conditional_id() -> None:
    # G1/G2/G3/N8/H15 are named in some rule's then.required, but inactive with no C3 answer, so
    # required_questions leaves them out too, whatever that rule lists.
    assert not required_questions(SCHEMA, {}) & {"G1", "G2", "G3", "N8", "H15"}


def test_story_3_1_required_questions_never_includes_d1() -> None:
    assert "D1" not in required_questions(SCHEMA, {"D1": True})


def test_story_1_7_d1_is_recognised_by_x_fill_not_by_its_id() -> None:
    schema = freeze(
        {
            "properties": {
                "A": {"type": "string", "x-fill": "ask"},
                "B": {"type": "string", "x-fill": "ask"},
                "SIGN": {"type": "boolean", "x-fill": "human"},
            },
            "allOf": [
                {
                    "if": {"properties": {"A": {"const": "Yes"}}, "required": ["A"]},
                    "then": {"required": ["B", "SIGN"]},
                },
                {"if": {"properties": {"A": {"const": "No"}}}},
            ],
        }
    )
    answers = {"A": "Yes", "SIGN": True}

    assert active_questions(schema, answers) == {"A", "B"}
    assert inactive_answer_ids(schema, {"SIGN": True, "B": "x"}) == {"B"}
