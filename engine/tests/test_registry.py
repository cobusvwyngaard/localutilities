from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import SAMPLE_TOOL, SHIPPED_REGISTRY
from werkbank_engine.registry import ParamError, RegistryError, ToolDef, load_registry, validate_params

TOOL = ToolDef.model_validate(SAMPLE_TOOL)


def test_shipped_registry_loads() -> None:
    registry = load_registry(SHIPPED_REGISTRY)
    assert registry.schemaVersion == 1
    assert {c.id for c in registry.categories} >= {"download", "video", "audio", "pdf"}


def test_missing_registry_explains_how_to_generate_it(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="gen:registry"):
        load_registry(tmp_path / "nope.json")


def test_registry_rejects_unknown_fields(tmp_path: Path) -> None:
    data = json.loads(SHIPPED_REGISTRY.read_text(encoding="utf-8"))
    data["tools"] = [{**SAMPLE_TOOL, "shell": "rm -rf /"}]
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(path)


def test_defaults_are_filled_in() -> None:
    assert validate_params(TOOL, {}) == {
        "preset": "balanced",
        "targetMb": 25,
        "crf": 23.5,
        "hardware": False,
        "title": "",
    }


def test_valid_params_pass_through() -> None:
    params = {"preset": "share", "targetMb": 100.0, "crf": 18, "hardware": True, "title": "My clip"}
    result = validate_params(TOOL, params)
    assert result["targetMb"] == 100
    assert isinstance(result["targetMb"], int)
    assert result["title"] == "My clip"


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"unknown": 1}, "unknown parameter"),
        ({"preset": "ultra"}, "must be one of"),
        ({"preset": 1}, "must be one of"),
        ({"targetMb": 0}, "between"),
        ({"targetMb": 4001}, "between"),
        ({"targetMb": 12.5}, "whole number"),
        ({"targetMb": True}, "must be a number"),
        ({"targetMb": "25"}, "must be a number"),
        ({"targetMb": 10**400}, "between"),
        ({"crf": float("nan")}, "finite"),
        ({"crf": float("inf")}, "finite"),
        ({"hardware": 1}, "true or false"),
        ({"hardware": "true"}, "true or false"),
        ({"title": "x" * 21}, "at most 20"),
        ({"title": "a\x00b"}, "control characters"),
        ({"title": ["list"]}, "must be text"),
    ],
)
def test_bad_params_are_rejected(params: dict, message: str) -> None:
    with pytest.raises(ParamError, match=message):
        validate_params(TOOL, params)


def test_params_must_be_an_object() -> None:
    with pytest.raises(ParamError):
        validate_params(TOOL, ["preset", "share"])
