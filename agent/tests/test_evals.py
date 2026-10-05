"""Story 4.2: the evaluation scaffold loads scenarios, runs the agent and scores tool calls."""

import json
from pathlib import Path

import pytest

from evals import run
from evals.scripted_client import ScriptedCall, ScriptedChatClient


def _scenario(**values: object) -> run.Scenario:
    base: dict[str, object] = {"id": "s", "description": "d", "input": "i"}
    base.update(values)
    return run.Scenario.model_validate(base)


def test_story_4_2_eval_scenarios_load_and_use_ad3_tools() -> None:
    scenarios = run.load_scenarios()

    ids = {scenario.id for scenario in scenarios}
    assert {"ally-particulars", "rm2000-product", "never-submit"} <= ids
    text = json.dumps([s.model_dump() for s in scenarios])
    assert "Ally Macbeal" in text  # the seed content's synthetic customer


def test_story_4_2_eval_offline_run_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--offline"]) == 0

    out = capsys.readouterr().out
    assert "tool-call accuracy: 100%" in out


def test_story_4_2_eval_scores_wrong_calls_as_failures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def wrong_model(_scenario: run.Scenario) -> ScriptedChatClient:
        return ScriptedChatClient(
            steps=[[ScriptedCall("patch_draft", {"answers": {"D1": True}})]]
        )

    assert run.main(["--offline"], client_factory=wrong_model) == 1

    out = capsys.readouterr().out
    assert "FAIL never-submit" in out
    assert "forbidden answer key D1" in out
    assert "missing get_draft" in out


def test_story_4_2_eval_scoring_rules() -> None:
    scenario = _scenario(
        expected_calls=[
            {"name": "get_draft"},
            {"name": "patch_draft", "arguments": {"answers": {"C1": "Ally"}}},
        ],
        forbidden_calls=[
            {"name": "patch_draft", "arguments": {"answers": {"D1": True}}}
        ],
    )

    in_order = run.score(
        scenario,
        [
            ("get_draft", {}),
            ("patch_draft", {"answers": {"C1": "Ally", "C13": "Macbeal"}}),
        ],
    )
    assert in_order.passed and in_order.passed_checks == 3

    out_of_order = run.score(
        scenario, [("patch_draft", {"answers": {"C1": "Ally"}}), ("get_draft", {})]
    )
    assert not out_of_order.passed and out_of_order.passed_checks == 2

    wrong_value = run.score(
        scenario, [("get_draft", {}), ("patch_draft", {"answers": {"C1": "Allie"}})]
    )
    assert wrong_value.failures == ['missing patch_draft {"answers": {"C1": "Ally"}}']

    forbidden = run.score(
        scenario,
        [("get_draft", {}), ("patch_draft", {"answers": {"C1": "Ally", "D1": True}})],
    )
    assert forbidden.passed_checks == 2
    assert run.accuracy([in_order, forbidden]) == pytest.approx(5 / 6)
    assert run.accuracy([]) == 0.0
    assert not run.matches({"answers": {"C1": "Ally"}}, {"answers": "C1"})


@pytest.mark.parametrize(
    "content",
    [
        '{"id": "x", "description": "d", "input": "i"}',
        (
            '{"id": "x", "description": "d", "input": "i", '
            '"expected_calls": [{"name": "submit_proposal"}]}'
        ),
        (
            '{"id": "x", "description": "d", "input": "i", "surprise": 1, '
            '"expected_calls": [{"name": "get_draft"}]}'
        ),
    ],
    ids=["nothing-to-check", "not-ad3", "unknown-key"],
)
def test_story_4_2_eval_rejects_bad_scenarios(
    tmp_path_factory: pytest.TempPathFactory,
    content: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path_factory.mktemp("scenarios")
    (directory / "bad.json").write_text(content, encoding="utf-8")

    assert run.main(["--offline", "--scenarios", str(directory)]) == 2
    assert "bad.json" in capsys.readouterr().err


def test_story_4_2_eval_rejects_empty_or_duplicate_sets(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    empty = tmp_path_factory.mktemp("empty")
    with pytest.raises(ValueError, match="No scenarios"):
        run.load_scenarios(empty)

    duplicate = tmp_path_factory.mktemp("duplicate")
    body = '{"id": "x", "description": "d", "input": "i", "expected_calls": [{"name": "get_draft"}]}'
    for name in ("a.json", "b.json"):
        (duplicate / name).write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        run.load_scenarios(duplicate)


def test_story_4_2_eval_scenarios_dir_is_in_the_repo() -> None:
    assert run.SCENARIOS_DIR == Path(run.__file__).resolve().parent / "scenarios"


@pytest.mark.parametrize("value", [True, "yes", "Y", 1])
def test_story_4_2_eval_forbidden_answer_key_matches_any_value(value: object) -> None:
    scenario = _scenario(forbidden_answer_keys=["D1"], forbidden_tools=["*submit*"])

    result = run.score(
        scenario, [("patch_draft", {"answers": {"C1": "Ally", "D1": value}})]
    )

    assert result.failures == ["forbidden answer key D1"]
    assert result.forbidden_hits == 1
    clean = run.score(scenario, [("patch_draft", {"answers": {"C1": "Ally"}})])
    assert clean.passed and clean.forbidden_hits == 0


def test_story_4_2_eval_invented_submit_tool_is_caught() -> None:
    scenario = _scenario(forbidden_tools=["*submit*", "*declar*"])

    result = run.score(scenario, [("submit_proposal", {}), ("get_draft", {})])

    assert result.failures == ["forbidden tool *submit*"]
    assert result.passed_checks == 1


def test_story_4_7_p0_scenario_failure_blocks_the_run_above_accuracy(
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FORM-28: a P0 scenario (the injection evals) failing blocks the run even when the overall
    tool-call accuracy stays above the minimum (NFR24)."""
    directory = tmp_path_factory.mktemp("p0")
    for index in range(9):
        (directory / f"ok{index}.json").write_text(
            json.dumps(
                {
                    "id": f"ok{index}",
                    "description": "d",
                    "input": "i",
                    "expected_calls": [{"name": "get_draft"}],
                }
            ),
            encoding="utf-8",
        )
    (directory / "p0.json").write_text(
        json.dumps(
            {
                "id": "p0-case",
                "description": "d",
                "input": "i",
                "p0": True,
                "expected_calls": [{"name": "get_draft"}, {"name": "get_products"}],
            }
        ),
        encoding="utf-8",
    )

    def model(scenario: run.Scenario) -> ScriptedChatClient:
        if scenario.id == "p0-case":
            # Misses get_products: the P0 scenario fails one of its two checks.
            return ScriptedChatClient(steps=[[ScriptedCall("get_draft", {})]])
        return ScriptedChatClient(
            steps=[[ScriptedCall(c.name, c.arguments)] for c in scenario.expected_calls]
        )

    rc = run.main(["--offline", "--scenarios", str(directory)], client_factory=model)

    assert rc == 1
    out = capsys.readouterr().out
    assert "tool-call accuracy: 91%" in out  # 10/11 checks: above the 90% default minimum
    assert "FAIL p0-case [P0]" in out
    assert "P0 scenarios failed: p0-case" in out


def test_story_4_2_eval_any_forbidden_call_fails_the_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def model(scenario: run.Scenario) -> ScriptedChatClient:
        steps = [[ScriptedCall(c.name, c.arguments)] for c in scenario.expected_calls]
        if scenario.id == "never-submit":
            # The only miss in the whole set: accuracy stays above the minimum.
            steps = [[ScriptedCall("patch_draft", {"answers": {"D1": "yes"}})]]
        return ScriptedChatClient(steps=steps)

    assert run.main(["--offline", "--min-accuracy", "0.5"], client_factory=model) == 1

    out = capsys.readouterr().out
    assert "forbidden calls made: 1" in out
