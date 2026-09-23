"""The tool registry (packages/shared/dist/tools.json) and strict parameter validation.

The registry is authored in TypeScript and exported to JSON; the engine never trusts the client's
parameters: unknown keys are rejected, enums must match, numbers must be in range (CLAUDE.md).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SCHEMA_VERSION = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EnumOption(_Strict):
    value: str
    label: str


class EnumParam(_Strict):
    type: Literal["enum"]
    label: str
    options: list[EnumOption]
    default: str


class NumberParam(_Strict):
    type: Literal["number"]
    label: str
    min: float
    max: float
    default: float
    integer: bool = False
    step: float | None = None
    unit: str | None = None


class BooleanParam(_Strict):
    type: Literal["boolean"]
    label: str
    default: bool


class TextParam(_Strict):
    type: Literal["text"]
    label: str
    maxLength: int
    default: str | None = None
    placeholder: str | None = None


ParamDef = Annotated[EnumParam | NumberParam | BooleanParam | TextParam, Field(discriminator="type")]


class InputSpec(_Strict):
    kinds: list[Literal["file", "url"]]
    accept: list[str] | None = None
    min: int
    max: int


class ToolDef(_Strict):
    id: str
    title: str
    description: str
    category: str
    runsIn: list[Literal["browser", "engine"]]
    inputs: InputSpec
    params: dict[str, ParamDef]
    requires: list[str]
    browserLimitBytes: int | None = None


class CategoryDef(_Strict):
    id: str
    title: str


class RegistryFile(_Strict):
    schemaVersion: Literal[1]
    categories: list[CategoryDef]
    dependencyIds: list[str]
    tools: list[ToolDef]


class RegistryError(ValueError):
    pass


class ParamError(ValueError):
    """A client-supplied parameter set failed validation; the message is safe to show."""


def load_registry(path: Path) -> RegistryFile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"{path} not found. Run `npm run gen:registry`.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read {path}: {exc}") from exc
    try:
        registry = RegistryFile.model_validate(data)
    except ValidationError as exc:
        raise RegistryError(f"{path} does not match the registry schema: {exc}") from exc
    ids = [t.id for t in registry.tools]
    if len(ids) != len(set(ids)):
        raise RegistryError(f"{path}: duplicate tool ids")
    return registry


def validate_params(tool: ToolDef, params: Any) -> dict[str, Any]:
    """Return a complete, validated parameter dict (defaults filled in) or raise ParamError."""
    if not isinstance(params, dict):
        raise ParamError("params must be an object")
    unknown = sorted(set(params) - set(tool.params))
    if unknown:
        raise ParamError(f"unknown parameter(s): {', '.join(unknown)}")

    result: dict[str, Any] = {}
    for key, spec in tool.params.items():
        if key not in params:
            if isinstance(spec, TextParam):
                result[key] = spec.default or ""
            elif isinstance(spec, NumberParam) and spec.integer:
                result[key] = int(spec.default)
            else:
                result[key] = spec.default
            continue
        value = params[key]
        match spec:
            case EnumParam():
                allowed = [o.value for o in spec.options]
                if not isinstance(value, str) or value not in allowed:
                    raise ParamError(f"{key}: must be one of {', '.join(allowed)}")
                result[key] = value
            case NumberParam():
                # bool is an int subclass in Python; reject it explicitly.
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise ParamError(f"{key}: must be a number")
                if isinstance(value, float) and not math.isfinite(value):
                    raise ParamError(f"{key}: must be a finite number")
                if not spec.min <= value <= spec.max:
                    raise ParamError(f"{key}: must be between {spec.min:g} and {spec.max:g}")
                if spec.integer:
                    if not float(value).is_integer():
                        raise ParamError(f"{key}: must be a whole number")
                    value = int(value)
                result[key] = value
            case BooleanParam():
                if not isinstance(value, bool):
                    raise ParamError(f"{key}: must be true or false")
                result[key] = value
            case TextParam():
                if not isinstance(value, str):
                    raise ParamError(f"{key}: must be text")
                if len(value) > spec.maxLength:
                    raise ParamError(f"{key}: must be at most {spec.maxLength} characters")
                if any(ord(c) < 32 and c not in "\t\n" for c in value):
                    raise ParamError(f"{key}: contains control characters")
                result[key] = value
    return result
