"""Story 1.7: form-schema/v1.json holds the content draft's 48 questions as AD-7 defines them."""

import hashlib
from typing import Any

from domain.schema import load_schema, questions, thaw
from tests.support import FORM_SCHEMA_DIR

# Released files are immutable (AD-7): a change must be a new v2.json, never an edit of v1.json.
V1_SHA256 = "f69d86077cfcd40dc45ebf0d24e59e69e9c8d695def590c1f6817d49f07db2cd"

SCHEMA: dict[str, Any] = thaw(load_schema(1))
Q: dict[str, dict[str, Any]] = SCHEMA["properties"]

PAGES = {
    1: ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8"],
    2: ["P1", "P2", "P3"],
    3: ["Y1", "Y2", "Y3"],
    4: [
        "C1",
        "C13",
        "C2",
        "C3",
        "C4",
        "C5",
        "C6",
        "C7",
        "C8",
        "C9",
        "C14",
        "C15",
        "C10",
        "C11",
        "C12",
    ],
    5: [
        *(f"H{n}" for n in range(1, 15)),
        "G1",
        "G2",
        "G3",
        "H15",
    ],
}
CONDITIONAL = {"N4", "N7", "N8", "G1", "G2", "G3", "H15"}
OPTIONAL = {"N5", "P2", "C12", "D1"}
SIMPLE = {"Y3", *(f"H{n}" for n in range(7, 15)), "G1", "H15"}
# The content draft's Label column (x-checklist-label) for every Ask and DB question.
CHECKLIST_LABELS = {
    "N1": "Type of cover",
    "N2": "Yearly budget",
    "N3": "Dependents",
    "N4": "Number of dependents",
    "N6": "Tobacco use",
    "N7": "Tobacco type and amount",
    "N8": "Pregnancy plans",
    "C1": "First name",
    "C13": "Last name",
    "C2": "Date of birth",
    "C3": "Sex at birth",
    "C4": "Country of origin",
    "C5": "Country of residence",
    "C6": "ID or passport number",
    "C7": "Email",
    "C8": "Mobile",
    "C9": "Street address",
    "C14": "City",
    "C15": "Postcode",
    "C10": "Occupation",
    "C11": "Marital status",
    "C12": "Income range",
    "H1": "Height",
    "H2": "Weight",
    "H3": "Alcohol per week",
    "H4": "Hazardous activities",
    "H5": "Family history",
    "H6": "Serious diagnoses",
    "G2": "Pregnancy outcomes",
    "G3": "Pregnancy details",
}


def test_story_1_7_v1_file_is_pinned() -> None:
    digest = hashlib.sha256((FORM_SCHEMA_DIR / "v1.json").read_bytes()).hexdigest()

    assert digest == V1_SHA256


def test_story_1_7_v1_is_a_2020_12_schema_with_no_extra_answers() -> None:
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert SCHEMA["type"] == "object"
    assert SCHEMA["additionalProperties"] is False


def test_story_1_7_v1_has_48_questions_in_page_order() -> None:
    rows = [qid for page in sorted(PAGES) for qid in PAGES[page]]

    assert list(questions(load_schema(1))) == [*rows, "D1"]
    assert len(rows) == 47
    for page, ids in PAGES.items():
        assert [Q[qid]["x-page"] for qid in ids] == [page] * len(ids)


def test_story_1_7_d1_is_a_human_only_boolean_and_never_a_row() -> None:
    d1 = Q["D1"]

    assert d1["type"] == "boolean"
    assert d1["x-fill"] == "human"
    assert d1["x-agent-writable"] is False
    assert "x-page" not in d1
    assert "D1" not in SCHEMA["required"]
    assert [qid for qid, q in Q.items() if q.get("x-agent-writable") is False] == ["D1"]


def test_story_1_7_v1_required_flags_follow_the_content_draft() -> None:
    assert set(SCHEMA["required"]) == set(Q) - CONDITIONAL - OPTIONAL
    assert len(SCHEMA["required"]) == 37


def test_story_1_7_v1_show_if_rules() -> None:
    rules = [
        (
            rule["if"]["properties"],
            rule["if"]["required"],
            rule["then"]["required"],
            set(rule),
        )
        for rule in SCHEMA["allOf"]
    ]

    assert rules == [
        ({"N3": {"const": "Yes"}}, ["N3"], ["N4"], {"if", "then"}),
        ({"N6": {"const": "Yes"}}, ["N6"], ["N7"], {"if", "then"}),
        ({"C3": {"const": "female"}}, ["C3"], ["N8", "G1", "H15"], {"if", "then"}),
        ({"G1": {"const": "Yes"}}, ["G1"], ["G2", "G3"], {"if", "then"}),
    ]


def test_story_1_7_v1_fill_and_simple_totals() -> None:
    fills: dict[str, set[str]] = {}
    for qid, q in Q.items():
        fills.setdefault(q["x-fill"], set()).add(qid)

    assert {qid for qid, q in Q.items() if q.get("x-simple") is True} == SIMPLE
    assert fills["default"] == SIMPLE
    assert {fill: len(ids) for fill, ids in fills.items()} == {
        "ask": 15,
        "infer": 6,
        "default": 11,
        "db": 15,
        "human": 1,
    }
    assert fills["infer"] == {"N5", "P1", "P2", "P3", "Y1", "Y2"}
    assert fills["db"] == set(PAGES[4])


def test_story_1_7_every_ask_and_db_question_has_its_checklist_label() -> None:
    labelled = {
        qid: q["x-checklist-label"] for qid, q in Q.items() if "x-checklist-label" in q
    }

    assert labelled == CHECKLIST_LABELS
    assert {qid for qid, q in Q.items() if q["x-fill"] in ("ask", "db")} == set(
        CHECKLIST_LABELS
    )


def test_story_1_7_yes_no_questions_are_a_yes_no_string_enum() -> None:
    yes_no = {qid for qid, q in Q.items() if q.get("enum") == ["Yes", "No"]}

    assert yes_no == {"N3", "N6", "N8", "H6", *SIMPLE}
    for qid in yes_no:
        assert Q[qid]["type"] == "string", qid


def test_story_1_7_v1_value_types_and_ranges() -> None:
    assert Q["N4"].items() >= {"type": "integer", "minimum": 1, "maximum": 10}.items()
    assert Q["H1"].items() >= {"type": "number", "minimum": 100, "maximum": 250}.items()
    assert Q["H2"].items() >= {"type": "number", "minimum": 30, "maximum": 300}.items()
    for qid in ("N2", "N5"):
        assert Q[qid]["type"] == "number" and Q[qid]["exclusiveMinimum"] == 0, qid
        assert Q[qid]["maximum"] == 100_000_000, qid
    assert Q["C2"]["format"] == "date"
    assert Q["C2"]["x-age-range"] == {"min": 18, "max": 70}
    assert Q["C7"]["format"] == "email"
    # The pattern keeps jsonschema's loose email check in step with Ajv's.
    assert Q["C7"]["pattern"] == r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    assert Q["C8"]["pattern"] == r"^\+[1-9][0-9]{7,14}$"
    for qid in ("C1", "C13"):
        assert (Q[qid]["minLength"], Q[qid]["maxLength"]) == (1, 50), qid
    for qid in ("N7", "G3"):
        assert (Q[qid]["minLength"], Q[qid]["maxLength"]) == (1, 500), qid
    for qid in ("C6", "C9", "C14", "C15", "C10"):
        assert (Q[qid]["minLength"], Q[qid]["maxLength"]) == (1, 200), qid


def test_story_1_7_products_and_riders_are_codes_without_an_enum() -> None:
    assert Q["P1"]["type"] == Q["P3"]["type"] == "string"
    assert Q["P2"]["type"] == "array" and Q["P2"]["uniqueItems"] is True
    for q in (Q["P1"], Q["P2"], Q["P2"]["items"], Q["P3"]):
        assert "enum" not in q


def test_story_1_7_choices_are_code_enums_with_labels() -> None:
    assert Q["N1"]["x-labels"] == {
        "life": "Life",
        "life_health": "Life + Health",
        "health": "Health",
    }
    assert Q["C3"]["enum"] == ["male", "female"]
    assert Q["C11"]["enum"] == ["single", "married", "divorced", "widowed"]
    assert Q["C12"]["enum"] == ["under_30k", "30k_60k", "60k_100k", "over_100k"]
    assert Q["H3"]["enum"] == ["none", "1_7", "8_14", "15_plus"]
    assert Q["Y1"]["enum"] == ["monthly", "yearly"]
    assert Q["Y2"]["enum"] == ["credit_card", "direct_debit"]
    for qid, q in Q.items():
        if "enum" in q and q["enum"] != ["Yes", "No"]:
            assert list(q["x-labels"]) == q["enum"], qid


def test_story_1_7_multi_choices_are_unique_code_arrays() -> None:
    multi = {qid for qid, q in Q.items() if q["type"] == "array"}

    assert multi == {"P2", "H4", "H5", "G2"}
    for qid in ("H4", "H5", "G2"):
        q = Q[qid]
        assert q["uniqueItems"] is True and q["minItems"] == 1, qid
        assert list(q["x-labels"]) == q["items"]["enum"], qid
    assert Q["H4"]["x-exclusive"] == Q["H5"]["x-exclusive"] == ["none"]
    assert "x-exclusive" not in Q["G2"]


def test_story_1_7_countries_are_the_iso_3166_alpha_2_list() -> None:
    for qid in ("C4", "C5"):
        codes = Q[qid]["enum"]
        assert len(codes) == 249 and codes == sorted(set(codes)), qid
        assert all(len(code) == 2 and code.isupper() for code in codes), qid
        assert Q[qid]["x-labels"]["MY"] == "Malaysia"
        assert Q[qid]["x-labels"]["SG"] == "Singapore"
    assert Q["C4"]["x-labels"] == Q["C5"]["x-labels"]
