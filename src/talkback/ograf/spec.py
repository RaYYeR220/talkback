"""The vendored OGraf v1 schemas (graphic manifest + Server API), wired up for jsonschema."""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema_specifications import REGISTRY as METASCHEMAS
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

OGRAF_DIR = Path(os.environ.get("TALKBACK_OGRAF_DIR") or Path(__file__).resolve().parents[3] / "ograf")
SPEC_DIR = OGRAF_DIR / "spec"
GRAPHICS_DIR = OGRAF_DIR / "graphics"
RENDERER_DIR = OGRAF_DIR / "renderer"

SPEC_BASE = "https://ograf.ebu.io/v1/specification/"
MANIFEST_SCHEMA_ID = SPEC_BASE + "json-schemas/graphics/schema.json"
SERVER_API_ID = SPEC_BASE + "open-api/server-api.yaml"


def _str_keys(node: Any) -> Any:
    # YAML reads response codes (200, 404) as ints; JSON pointers need strings.
    if isinstance(node, dict):
        return {str(k): _str_keys(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_str_keys(v) for v in node]
    return node


@cache
def server_api() -> dict[str, Any]:
    return _str_keys(yaml.safe_load((SPEC_DIR / "open-api" / "server-api.yaml").read_text("utf-8")))


@cache
def registry() -> Registry:
    resources = []
    for path in sorted((SPEC_DIR / "json-schemas").rglob("*.json")):
        doc = json.loads(path.read_text("utf-8"))
        resources.append((doc["$id"], Resource.from_contents(doc)))
    resources.append((SERVER_API_ID, Resource(contents=server_api(), specification=DRAFT202012)))
    return METASCHEMAS.with_resources(resources)


@cache
def manifest_validator() -> Draft202012Validator:
    return Draft202012Validator({"$ref": MANIFEST_SCHEMA_ID}, registry=registry())


def _pointer(*parts: str) -> str:
    return "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


def api_validator(path: str, method: str, status: int | None = None) -> Draft202012Validator:
    """Validator for a Server API response body, or for the request body when `status` is None."""
    if status is None:
        ptr = _pointer("paths", path, method, "requestBody", "content", "application/json", "schema")
    else:
        ptr = _pointer("paths", path, method, "responses", str(status), "content", "application/json", "schema")
    return Draft202012Validator({"$ref": f"{SERVER_API_ID}#/{ptr}"}, registry=registry())


def component_validator(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"{SERVER_API_ID}#/components/schemas/{name}"}, registry=registry())
