"""Story 1.7: the schema lint passes v1 and fails each broken fixture on its own rule (AD-7)."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests.support import FORM_SCHEMA_DIR

LINT_PATH = FORM_SCHEMA_DIR / "lint.py"
FIXTURES = sorted((FORM_SCHEMA_DIR / "tests" / "fixtures").glob("*.json"))


def _load_lint() -> ModuleType:
    spec = importlib.util.spec_from_file_location("form_schema_lint", LINT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_lint()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rules(schema: Any) -> set[str]:
    return {failure.rule for failure in lint.lint(schema)}


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed interpreter and repo paths
        [sys.executable, str(LINT_PATH), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_story_1_7_lint_passes_v1() -> None:
    result = _run(FORM_SCHEMA_DIR / "v1.json")

    assert result.returncode == 0, result.stdout
    assert lint.lint(_read(FORM_SCHEMA_DIR / "v1.json")) == []


def test_story_1_7_there_is_a_failing_fixture_for_every_rule() -> None:
    assert {path.stem for path in FIXTURES} == {
        f"fail-{rule}"
        for rule in (
            "keywords",
            "metaschema",
            "simple",
            "human",
            "checklist-label",
            "page",
            "show-if",
            "labels",
            "totals",
        )
    }


@pytest.mark.parametrize("fixture", FIXTURES, ids=[path.stem for path in FIXTURES])
def test_story_1_7_lint_fails_each_broken_fixture_naming_its_rule(
    fixture: Path,
) -> None:
    rule = fixture.stem.removeprefix("fail-")

    result = _run(fixture)

    assert result.returncode == 1
    assert f"rule {rule}:" in result.stdout
    # Each fixture breaks exactly one rule, so a pass on the others is meaningful.
    assert _rules(_read(fixture)) == {rule}


@pytest.fixture
def v1() -> Any:
    return copy.deepcopy(_read(FORM_SCHEMA_DIR / "v1.json"))


def test_story_1_7_lint_rejects_array_items_and_non_object_schemas(v1: Any) -> None:
    v1["properties"]["P2"]["items"] = [{"type": "string"}]
    v1["properties"]["N5"] = 5

    assert {f.where for f in lint.lint(v1) if f.rule == "keywords"} == {
        "$.properties.P2",
        "$.properties.P2.items",
        "$.properties.N5",
    }


def test_story_1_7_lint_rejects_a_keyword_nested_in_a_show_if_rule(v1: Any) -> None:
    v1["allOf"][0]["then"]["properties"] = {"N4": {"not": {"const": 0}}}

    failures = [f for f in lint.lint(v1) if f.rule == "keywords"]

    assert [f.where for f in failures] == ["$.allOf[0].then.properties.N4"]


def test_story_1_7_lint_requires_the_declaration_to_stay_off_the_pages(
    v1: Any,
) -> None:
    v1["properties"]["D1"]["x-page"] = 5
    del v1["properties"]["N1"]["x-page"]

    assert {(f.rule, f.where) for f in lint.lint(v1)} == {
        ("page", "D1"),
        ("page", "N1"),
    }


def test_story_1_7_lint_rejects_simple_questions_that_are_not_yes_no(v1: Any) -> None:
    v1["properties"]["Y1"]["x-simple"] = True
    v1["properties"]["Y1"]["x-fill"] = "default"

    assert {(f.rule, f.where) for f in lint.lint(v1)} >= {("simple", "Y1")}


def test_story_1_7_lint_checks_x_labels_against_multi_choice_items(v1: Any) -> None:
    v1["properties"]["G2"]["x-labels"]["twins"] = "Twins"

    assert {(f.rule, f.where) for f in lint.lint(v1)} == {("labels", "G2")}


def test_story_1_7_lint_rejects_a_show_if_rule_without_then(v1: Any) -> None:
    del v1["allOf"][1]["then"]

    assert ("show-if", "allOf[1]") in {(f.rule, f.where) for f in lint.lint(v1)}


def test_story_1_7_lint_needs_a_known_version_and_fill(v1: Any) -> None:
    v1["$id"] = "urn:formapp:form-schema:v99"
    assert {(f.rule, f.where) for f in lint.lint(v1)} == {("totals", "$id")}

    v1["$id"] = "urn:formapp:form-schema:v1"
    v1["properties"]["N5"]["x-fill"] = "guess"
    assert ("totals", "N5") in {(f.rule, f.where) for f in lint.lint(v1)}


def test_story_1_7_lint_cli_reports_unreadable_files_and_usage(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")

    assert _run(broken).returncode == 1
    assert "rule json:" in _run(broken).stdout
    assert lint.main(["lint.py"]) == 2


def _show_if(schema: Any) -> set[str]:
    return {f.message for f in lint.lint(schema) if f.rule == "show-if"}


def test_story_1_7_lint_requires_every_tested_id_to_be_answered(v1: Any) -> None:
    # Without required, an unanswered N3 would pass the if and show N4.
    v1["allOf"][0]["if"]["required"] = []

    assert _show_if(v1) == {"if tests 'N3' but does not require it"}


def test_story_1_7_lint_lets_then_only_add_required(v1: Any) -> None:
    v1["allOf"][1]["then"]["properties"] = {"N7": {"minLength": 5}}

    assert _show_if(v1) == {"then may only hold required"}


def test_story_1_7_lint_rejects_an_always_required_question_in_then(v1: Any) -> None:
    v1["allOf"][2]["then"]["required"].append("C1")

    assert _show_if(v1) == {"'C1' is always required, so never conditional"}


def test_story_1_7_lint_rejects_the_human_question_in_a_show_if_rule(v1: Any) -> None:
    v1["allOf"][3]["then"]["required"].append("D1")

    assert _show_if(v1) == {"'D1' is an x-fill: human question"}


def test_story_1_7_lint_needs_a_label_for_every_code(v1: Any) -> None:
    del v1["properties"]["C11"]["x-labels"]["widowed"]
    del v1["properties"]["G2"]["x-labels"]["ectopic"]

    assert {(f.rule, f.where) for f in lint.lint(v1)} == {
        ("labels", "C11"),
        ("labels", "G2"),
    }


def test_story_1_7_lint_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    text = (FORM_SCHEMA_DIR / "v1.json").read_text(encoding="utf-8")
    # A second N1 would silently replace the first.
    duplicated = tmp_path / "duplicated.json"
    duplicated.write_text(
        text.replace('"properties": {', '"properties": {"N1": {}, ', 1),
        encoding="utf-8",
    )

    result = _run(duplicated)

    assert result.returncode == 1
    assert "rule json:" in result.stdout and "duplicate keys ['N1']" in result.stdout
