"""Story 1.7: the shared answer sets validate as expected against v1 with jsonschema (Decision 2).

Story 1.9 runs the same file through Ajv2020, so both validators agree on what v1 accepts.
"""

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

from domain.schema import load_schema, thaw
from tests.support import FORM_SCHEMA_DIR

CASES_FILE = json.loads(
    (FORM_SCHEMA_DIR / "tests" / "answers-cases.json").read_text(encoding="utf-8")
)
SCHEMA = thaw(load_schema(CASES_FILE["schema_version"], FORM_SCHEMA_DIR))
VALIDATOR = Draft202012Validator(
    SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER
)


def _answers(case: dict[str, Any]) -> dict[str, Any]:
    answers = {**CASES_FILE["base"], **case["answers"]}
    for qid in case.get("omit", []):
        answers.pop(qid, None)
    return answers


def _failing_ids(error: ValidationError, answers: dict[str, Any]) -> set[str]:
    """The question ids one validation error is about."""
    if error.absolute_path:
        return {str(error.absolute_path[0])}
    if error.validator == "required":
        required: list[str] = error.schema["required"]  # type: ignore[index]  # a dict here
        return {qid for qid in required if qid not in answers}
    if error.validator == "additionalProperties":
        return set(answers) - set(SCHEMA["properties"])
    raise AssertionError(f"Unexpected top-level error: {error.message}")


@pytest.mark.parametrize(
    "case", CASES_FILE["cases"], ids=[case["name"] for case in CASES_FILE["cases"]]
)
def test_story_1_7_shared_answer_cases_validate_as_expected(
    case: dict[str, Any],
) -> None:
    answers = _answers(case)

    failing: set[str] = set()
    for error in VALIDATOR.iter_errors(answers):
        failing |= _failing_ids(error, answers)

    assert sorted(failing) == sorted(case["errors"])


def test_story_1_7_answer_cases_cover_the_required_kinds() -> None:
    names = " ".join(case["name"] for case in CASES_FILE["cases"])
    valid = [case for case in CASES_FILE["cases"] if not case["errors"]]

    assert valid and len(valid) < len(CASES_FILE["cases"])
    for kind in (
        "code",
        "country",
        "height",
        "email",
        "E.164",
        "date",
        "repeated",
    ):
        assert kind in names, kind
