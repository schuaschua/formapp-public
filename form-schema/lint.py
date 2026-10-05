"""Lint a form schema file (spine AD-7). Usage: ``python lint.py <file>``.

Exit 0 when every rule passes; otherwise print one line per failure, each naming its rule, and exit 1.
Run from the api environment, which provides ``jsonschema``.
"""

import json
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator
from jsonschema.exceptions import SchemaError

# Keywords valid, with the same meaning, in both draft-07 and 2020-12 (AD-7). `items` is allowed only
# as one schema for every item: its array form means different things in the two drafts.
KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "const",
        "properties",
        "required",
        "additionalProperties",
        "if",
        "then",
        "allOf",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "items",
        "uniqueItems",
        "minItems",
        "title",
        "description",
        "$schema",
        "$id",
    }
)
EXTENSIONS = frozenset(
    {
        "x-page",
        "x-simple",
        "x-agent-writable",
        "x-fill",
        "x-labels",
        "x-exclusive",
        "x-age-range",
        "x-checklist-label",
    }
)
FILLS = frozenset({"ask", "infer", "default", "db", "human"})
YES_NO = ["Yes", "No"]

# Expected totals per released version: a changed count means a question was added, dropped or
# re-classified without updating this table on purpose.
TOTALS = {
    1: {"questions": 48, "simple": 11, "ask": 15, "infer": 6, "db": 15, "human": 1},
    # FORM-222/224: page 1 (Needs, N1-N4) dropped; N5-N8 move onto Product/Health & lifestyle;
    # Y1 (payment frequency) becomes an ask question (CAP-4: the checklist "including payment
    # frequency"), so ask +1/infer -1 versus a plain N1-N4 removal.
    2: {"questions": 44, "simple": 11, "ask": 12, "infer": 5, "db": 15, "human": 1},
}
_VERSION_ID = re.compile(r"^urn:formapp:form-schema:v([1-9][0-9]*)$")


@dataclass(frozen=True)
class Failure:
    rule: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"rule {self.rule}: {self.where}: {self.message}"


def _subschemas(node: dict[str, Any], where: str) -> Iterator[tuple[Any, str]]:
    for name, sub in node.get("properties", {}).items():
        yield sub, f"{where}.properties.{name}"
    for keyword in ("additionalProperties", "if", "then", "items"):
        if keyword in node:
            yield node[keyword], f"{where}.{keyword}"
    for index, sub in enumerate(node.get("allOf", [])):
        yield sub, f"{where}.allOf[{index}]"


def check_keywords(node: Any, where: str = "$") -> Iterator[Failure]:
    """Only allowlisted keywords and AD-7 extensions, at every level."""
    if isinstance(node, bool):
        return
    if not isinstance(node, dict):
        yield Failure("keywords", where, "a schema must be an object or a boolean")
        return
    for keyword in node:
        if keyword not in KEYWORDS and keyword not in EXTENSIONS:
            yield Failure("keywords", where, f"keyword {keyword!r} is not allowed")
    if "items" in node and not isinstance(node["items"], dict):
        yield Failure("keywords", where, "items must be one schema (an object)")
    for sub, sub_where in _subschemas(node, where):
        yield from check_keywords(sub, sub_where)


def check_metaschema(schema: Any) -> Iterator[Failure]:
    """The file is a valid schema under both drafts."""
    for validator in (Draft7Validator, Draft202012Validator):
        try:
            validator.check_schema(schema)
        except SchemaError as error:
            path = "".join(f"[{part!r}]" for part in error.absolute_path)
            yield Failure(
                "metaschema", f"${path}", f"{validator.__name__}: {error.message}"
            )


def _questions(schema: Any) -> dict[str, dict[str, Any]]:
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return {qid: q for qid, q in properties.items() if isinstance(q, dict)}


def check_implications(schema: Any) -> Iterator[Failure]:
    """AD-7's three implications."""
    for qid, q in _questions(schema).items():
        fill = q.get("x-fill")
        if q.get("x-simple") is True and not (
            q.get("type") == "string" and q.get("enum") == YES_NO and fill == "default"
        ):
            yield Failure(
                "simple", qid, "x-simple needs a Yes/No question with x-fill: default"
            )
        if fill == "human" and q.get("x-agent-writable") is not False:
            yield Failure("human", qid, "x-fill: human needs x-agent-writable: false")
        label = q.get("x-checklist-label")
        if fill in ("ask", "db") and not (isinstance(label, str) and label.strip()):
            yield Failure(
                "checklist-label", qid, f"x-fill: {fill} needs an x-checklist-label"
            )


def check_pages(schema: Any) -> Iterator[Failure]:
    """Every form row sits on page 1-5; the human declaration is never a row."""
    for qid, q in _questions(schema).items():
        page = q.get("x-page")
        if q.get("x-fill") == "human":
            if "x-page" in q:
                yield Failure(
                    "page", qid, "an x-fill: human question is never a form row"
                )
        elif not (type(page) is int and 1 <= page <= 5):
            yield Failure("page", qid, f"x-page must be an integer 1-5, got {page!r}")


def check_show_if(schema: Any) -> Iterator[Failure]:
    """Each rule is `if` answered-and-equal, `then` only adds conditional form rows (AD-15)."""
    questions = _questions(schema)
    always = set(schema.get("required", [])) if isinstance(schema, dict) else set()
    rules = schema.get("allOf", []) if isinstance(schema, dict) else []
    for index, rule in enumerate(rules):
        where = f"allOf[{index}]"
        if not isinstance(rule, dict):
            continue
        condition, then = rule.get("if"), rule.get("then")
        if not (isinstance(condition, dict) and isinstance(then, dict)):
            yield Failure("show-if", where, "needs an if and a then object")
            continue
        tested = list(condition.get("properties", {}))
        answered = list(condition.get("required", []))
        shown = list(then.get("required", []))
        for qid in [*tested, *answered, *shown]:
            if qid not in questions:
                yield Failure("show-if", where, f"{qid!r} is not a question")
            elif questions[qid].get("x-fill") == "human":
                yield Failure("show-if", where, f"{qid!r} is an x-fill: human question")
        # Without required, an unanswered question passes the if and shows the then rows.
        for qid in sorted(set(tested) - set(answered)):
            yield Failure("show-if", where, f"if tests {qid!r} but does not require it")
        if set(then) != {"required"}:
            yield Failure("show-if", where, "then may only hold required")
        for qid in shown:
            if qid in always:
                yield Failure(
                    "show-if",
                    where,
                    f"{qid!r} is always required, so never conditional",
                )


def check_labels(schema: Any) -> Iterator[Failure]:
    """x-labels and x-exclusive name only enum codes; x-labels names every code."""
    for qid, q in _questions(schema).items():
        items = q.get("items")
        enum = q.get("enum") or (items.get("enum") if isinstance(items, dict) else None)
        codes = set(enum or [])
        for extension in ("x-labels", "x-exclusive"):
            if isinstance(q.get(extension), dict | list):
                unknown = set(q[extension]) - codes
                if unknown:
                    yield Failure(
                        "labels",
                        qid,
                        f"{extension} names codes not in the enum: {sorted(unknown)}",
                    )
        labels = q.get("x-labels")
        if isinstance(labels, dict) and enum != YES_NO:
            unlabelled = [code for code in enum or [] if code not in labels]
            if unlabelled:
                yield Failure("labels", qid, f"x-labels has no label for {unlabelled}")


def check_totals(schema: Any) -> Iterator[Failure]:
    """Question counts per x-fill and x-simple match the version's table."""
    questions = _questions(schema)
    for qid, q in questions.items():
        if q.get("x-fill") not in FILLS:
            yield Failure("totals", qid, f"x-fill must be one of {sorted(FILLS)}")
    match = (
        _VERSION_ID.match(str(schema.get("$id", "")))
        if isinstance(schema, dict)
        else None
    )
    expected = TOTALS.get(int(match[1])) if match else None
    if expected is None:
        yield Failure("totals", "$id", "no totals for this schema's $id")
        return
    fills = Counter(q.get("x-fill") for q in questions.values())
    actual = {
        "questions": len(questions),
        "simple": sum(q.get("x-simple") is True for q in questions.values()),
        **{fill: fills[fill] for fill in ("ask", "infer", "db", "human")},
    }
    for name, count in expected.items():
        if actual[name] != count:
            yield Failure("totals", name, f"expected {count}, found {actual[name]}")


def lint(schema: Any) -> list[Failure]:
    """Every rule's failures for one parsed schema."""
    return [
        *check_keywords(schema),
        *check_metaschema(schema),
        *check_implications(schema),
        *check_pages(schema),
        *check_show_if(schema),
        *check_labels(schema),
        *check_totals(schema),
    ]


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """A JSON object hook: a repeated key would silently drop a question or keyword."""
    keys = [key for key, _ in pairs]
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise ValueError(f"duplicate keys {repeated}")
    return dict(pairs)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python lint.py <schema.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        schema = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates
        )
    except (OSError, ValueError) as error:
        print(f"rule json: {path}: {error}")
        return 1
    failures = lint(schema)
    for failure in failures:
        print(failure)
    if failures:
        return 1
    print(f"{path}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
