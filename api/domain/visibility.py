"""The active (show-if) set of a proposal (spine AD-15).

A question named in some ``allOf[].then.required`` of the schema is conditional: it is active only
while that rule's ``if`` holds. Conditions are evaluated only against answers to questions that are
already active, repeated until nothing changes, so a stale answer to an inactive question never
activates anything (C3 = male leaves G1 inactive, and so G2 and G3 too, whatever G1 holds).

``x-fill: human`` questions (D1) are never active and never removed as inactive answers: only the
submit transaction sets D1 (FR18, AD-8).
"""

from collections.abc import Iterator, Mapping
from typing import Any

from jsonschema import Draft202012Validator

from domain.schema import Schema, questions, thaw


def _is_human(question: Mapping[str, Any]) -> bool:
    return question.get("x-fill") == "human"


def _rules(schema: Schema) -> Iterator[tuple[Draft202012Validator, tuple[str, ...]]]:
    for rule in schema.get("allOf", ()):
        if "if" in rule and "then" in rule:
            condition = Draft202012Validator(thaw(rule["if"]))
            yield condition, tuple(rule["then"].get("required", ()))


def active_questions(schema: Schema, answers: Mapping[str, object]) -> frozenset[str]:
    """Return the ids of the questions shown for these answers (question id -> value)."""
    rules = list(_rules(schema))
    conditional = {qid for _, shown in rules for qid in shown}
    human = {qid for qid, question in questions(schema).items() if _is_human(question)}
    active = {
        qid for qid in questions(schema) if qid not in conditional and qid not in human
    }
    changed = True
    while changed:
        changed = False
        visible = {qid: value for qid, value in answers.items() if qid in active}
        for condition, shown in rules:
            added = set(shown) - active - human
            if added and condition.is_valid(visible):
                active |= added
                changed = True
    return frozenset(active)


def inactive_answer_ids(
    schema: Schema, answers: Mapping[str, object]
) -> frozenset[str]:
    """Return the answered questions that are inactive and must be removed (never D1)."""
    active = active_questions(schema, answers)
    return frozenset(
        qid
        for qid, question in questions(schema).items()
        if qid in answers and qid not in active and not _is_human(question)
    )


def required_questions(schema: Schema, answers: Mapping[str, object]) -> frozenset[str]:
    """Return the active questions that are required right now (spine AD-7, Story 3.1 design
    notes): the schema's top-level ``required`` union every ``allOf`` rule's own ``then.required``
    (a conditional question is required exactly when its rule's ``if`` makes it active, since that
    same ``then.required`` is what activates it), intersected with :func:`active_questions`. D1 is
    never included: it is never active.
    """
    top_required = frozenset(schema.get("required", ()))
    conditional = frozenset(qid for _, shown in _rules(schema) for qid in shown)
    return (top_required | conditional) & active_questions(schema, answers)
