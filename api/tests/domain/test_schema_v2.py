"""FORM-222/224: form-schema/v2.json drops page 1 (Needs, N1-N4), moves N5-N8 onto the
Product/Health & lifestyle pages, restricts H4 to none/other, and reclassifies Y1 (payment
frequency) as an ask question (CAP-4: the checklist "including payment frequency"). Mirrors
test_schema_v1.py's own rigor for the new released version (AD-7)."""

import hashlib
from typing import Any

from domain.schema import load_schema, questions, thaw
from tests.support import FORM_SCHEMA_DIR

# Released files are immutable (AD-7): a change must be a new v3.json, never an edit of v2.json.
V2_SHA256 = "afd0f779e9a3e4e0397fd9e1c29959e2074b337278c4caf8f6acd786e7a3f9b8"

SCHEMA: dict[str, Any] = thaw(load_schema(2))
Q: dict[str, dict[str, Any]] = SCHEMA["properties"]

PAGES = {
    1: ["N5", "P1", "P2", "P3"],
    2: ["Y1", "Y2", "Y3"],
    3: [
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
    4: [
        "N6",
        "N7",
        "N8",
        *(f"H{n}" for n in range(1, 15)),
        "G1",
        "G2",
        "G3",
        "H15",
    ],
}
CONDITIONAL = {"N7", "N8", "G1", "G2", "G3", "H15"}
OPTIONAL = {"N5", "P2", "C12", "D1"}
SIMPLE = {"Y3", *(f"H{n}" for n in range(7, 15)), "G1", "H15"}
# The content draft's Label column (x-checklist-label) for every Ask and DB question.
CHECKLIST_LABELS = {
    "N6": "Tobacco use",
    "N7": "Tobacco type and amount",
    "N8": "Pregnancy plans",
    "Y1": "Payment frequency",
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


def test_form_222_v2_file_is_pinned() -> None:
    digest = hashlib.sha256((FORM_SCHEMA_DIR / "v2.json").read_bytes()).hexdigest()

    assert digest == V2_SHA256


def test_form_222_v2_is_a_2020_12_schema_with_no_extra_answers() -> None:
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert SCHEMA["$id"] == "urn:formapp:form-schema:v2"
    assert SCHEMA["type"] == "object"
    assert SCHEMA["additionalProperties"] is False


def test_form_222_v2_has_44_questions_in_page_order() -> None:
    rows = [qid for page in sorted(PAGES) for qid in PAGES[page]]

    assert list(questions(load_schema(2))) == [*rows, "D1"]
    assert len(rows) == 43
    for page, ids in PAGES.items():
        assert [Q[qid]["x-page"] for qid in ids] == [page] * len(ids)


def test_form_222_v2_dropped_the_needs_page() -> None:
    assert not ({"N1", "N2", "N3", "N4"} & set(Q))


def test_form_222_d1_is_a_human_only_boolean_and_never_a_row() -> None:
    d1 = Q["D1"]

    assert d1["type"] == "boolean"
    assert d1["x-fill"] == "human"
    assert d1["x-agent-writable"] is False
    assert "x-page" not in d1
    assert "D1" not in SCHEMA["required"]
    assert [qid for qid, q in Q.items() if q.get("x-agent-writable") is False] == ["D1"]


def test_form_222_v2_required_flags_follow_the_content_draft() -> None:
    assert set(SCHEMA["required"]) == set(Q) - CONDITIONAL - OPTIONAL
    assert len(SCHEMA["required"]) == 34


def test_form_222_v2_show_if_rules() -> None:
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
        ({"N6": {"const": "Yes"}}, ["N6"], ["N7"], {"if", "then"}),
        ({"C3": {"const": "female"}}, ["C3"], ["N8", "G1", "H15"], {"if", "then"}),
        ({"G1": {"const": "Yes"}}, ["G1"], ["G2", "G3"], {"if", "then"}),
    ]


def test_form_222_v2_fill_and_simple_totals() -> None:
    fills: dict[str, set[str]] = {}
    for qid, q in Q.items():
        fills.setdefault(q["x-fill"], set()).add(qid)

    assert {qid for qid, q in Q.items() if q.get("x-simple") is True} == SIMPLE
    assert fills["default"] == SIMPLE
    assert {fill: len(ids) for fill, ids in fills.items()} == {
        "ask": 12,
        "infer": 5,
        "default": 11,
        "db": 15,
        "human": 1,
    }
    assert fills["infer"] == {"N5", "P1", "P2", "P3", "Y2"}
    assert fills["db"] == set(PAGES[3])


def test_form_222_y1_is_now_an_ask_question() -> None:
    """CAP-4: the checklist matches the schema's ask questions, "including payment frequency"."""
    assert Q["Y1"]["x-fill"] == "ask"
    assert Q["Y1"]["x-checklist-label"] == "Payment frequency"


def test_form_222_every_ask_and_db_question_has_its_checklist_label() -> None:
    labelled = {
        qid: q["x-checklist-label"] for qid, q in Q.items() if "x-checklist-label" in q
    }

    assert labelled == CHECKLIST_LABELS
    assert {qid for qid, q in Q.items() if q["x-fill"] in ("ask", "db")} == set(
        CHECKLIST_LABELS
    )


def test_form_224_h4_is_restricted_to_none_or_other() -> None:
    h4 = Q["H4"]

    assert h4["items"]["enum"] == ["none", "other"]
    assert h4["x-labels"] == {"none": "None", "other": "Other"}
    assert h4["x-exclusive"] == ["none"]
    assert h4["uniqueItems"] is True and h4["minItems"] == 1


def test_form_222_v2_countries_are_unchanged_from_v1() -> None:
    v1 = thaw(load_schema(1))["properties"]
    for qid in ("C4", "C5"):
        assert Q[qid]["enum"] == v1[qid]["enum"]
        assert Q[qid]["x-labels"] == v1[qid]["x-labels"]
