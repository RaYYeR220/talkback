import json
import re
import shutil
import subprocess

import pytest

from talkback.ograf.spec import GRAPHICS_DIR, MANIFEST_SCHEMA_ID, manifest_validator

IDS = ["talkback-scorebug", "talkback-lower-third", "talkback-stat-card", "talkback-story-card",
       "talkback-counterfactual-card", "talkback-table-swing", "talkback-player-tag", "talkback-ifb"]
METHODS = ["load", "dispose", "playAction", "stopAction", "updateAction", "customAction"]
BASE_START = "// ---- talkback ograf base: keep this block identical in every graphic ----"
BASE_END = "// ---- end talkback ograf base ----"
NODE = shutil.which("node")


def manifest(gid: str) -> dict:
    return json.loads((GRAPHICS_DIR / gid / "graphic.ograf.json").read_text("utf-8"))


def source(gid: str) -> str:
    return (GRAPHICS_DIR / gid / "graphic.mjs").read_text("utf-8")


def test_every_graphic_ships():
    assert sorted(p.parent.name for p in GRAPHICS_DIR.glob("*/*.ograf.json")) == sorted(IDS)


@pytest.mark.parametrize("gid", IDS)
def test_manifest_validates_against_the_official_schema(gid):
    m = manifest(gid)
    assert m["$schema"] == MANIFEST_SCHEMA_ID
    assert [f"{list(e.absolute_path)}: {e.message}" for e in manifest_validator().iter_errors(m)] == []


def test_validator_rejects_broken_manifests():
    m = manifest("talkback-stat-card")
    del m["supportsRealTime"]
    m["schema"]["properties"]["value"]["type"] = ["string", "null"]
    m["schema"]["properties"]["unit"]["gddType"] = "color-rrggbb"
    assert len(list(manifest_validator().iter_errors(m))) >= 3


@pytest.mark.parametrize("gid", IDS)
def test_manifest_contract(gid):
    m = manifest(gid)
    assert m["id"] == gid
    assert (GRAPHICS_DIR / gid / m["main"]).is_file()
    assert m["supportsRealTime"] is True and m["supportsNonRealTime"] is False
    props = m["schema"]["properties"]
    assert props["dir"]["enum"] == ["ltr", "rtl"]
    assert m["schema"]["type"] == "object" and len(props) >= 4
    custom = {a["id"] for a in m.get("customActions", [])}
    timed = {d["customActionId"] for d in m["actionDurations"] if d["type"] == "customAction"}
    assert custom == timed


@pytest.mark.parametrize("gid", IDS)
def test_module_exports_a_web_component_with_the_ograf_interface(gid):
    src = source(gid)
    assert re.search(r"^export default class \w+ extends TalkbackGraphic \{", src, re.MULTILINE)
    assert "class TalkbackGraphic extends HTMLElement {" in src
    for name in METHODS:
        assert re.search(rf"^  async {name}\(", src, re.MULTILINE), name
    assert "customElements.define" not in src, "the renderer registers the element; graphics only export it"
    assert "innerHTML = `<style>" in src and "textContent" in src


def test_shared_base_block_is_identical_everywhere():
    blocks = set()
    for gid in IDS:
        src = source(gid)
        start, end = src.index(BASE_START), src.index(BASE_END)
        blocks.add(src[start:end])
    assert len(blocks) == 1


@pytest.mark.parametrize("gid", IDS)
def test_no_external_assets(gid):
    urls = re.findall(r"https?://[^\s\"'`)]+", source(gid))
    assert all(u.startswith("https://ograf.ebu.io/") for u in urls), urls


@pytest.mark.parametrize("gid", IDS)
def test_styling_is_themeable(gid):
    src = source(gid)
    colours = re.findall(r"#[0-9a-fA-F]{3,8}\b", src[src.index(BASE_END):])
    assert colours == [], f"hard-coded colours outside the token block: {colours}"
    assert "var(--tb-accent" in src and "tabular-nums" in src


NODE_CHECK = r"""
globalThis.HTMLElement = class {
  attachShadow() { return { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] }; }
};
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
const METHODS = %s;
// Rows of the step table in the OGraf Graphics spec: [current, stepCount, goto, delta, target]
const TABLE = [[null,1,null,null,0],[null,1,0,null,0],[null,1,null,1,0],[null,2,1,2,1],[0,2,1,null,1],
               [0,3,null,2,2],[2,3,1,null,1],[2,3,null,-2,0],[0,1,null,1,null]];
const u = (v) => (v === null ? undefined : v);
const out = [];
for (const url of process.argv.slice(2)) {
  const Cls = (await import(url)).default;
  const g = new Cls();
  const steps = TABLE.map(([cur, count, goto, delta]) => {
    Cls.stepCount = count;
    g._step = u(cur);
    const t = g._targetStep({ goto: u(goto), delta: u(delta) });
    return t === undefined ? null : t;
  });
  delete Cls.stepCount;
  out.push({
    name: Cls.name, element: Cls.prototype instanceof HTMLElement, stepCount: Cls.stepCount,
    methods: METHODS.filter((m) => typeof g[m] === "function"), steps, expected: TABLE.map((r) => r[4]),
    nonRealtime: (await g.load({ data: {}, renderType: "non-realtime" })).statusCode,
    unknownCustom: (await g.customAction({ id: "no-such-action", payload: {} })).statusCode,
  });
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_web_components_run_the_spec_step_model(tmp_path):
    script = tmp_path / "check.mjs"
    script.write_text(NODE_CHECK % json.dumps(METHODS), encoding="utf-8")
    urls = [(GRAPHICS_DIR / gid / "graphic.mjs").as_uri() for gid in IDS]
    run = subprocess.run([NODE, str(script), *urls], capture_output=True, text=True, timeout=60, check=False)
    assert run.returncode == 0, run.stderr
    for gid, r in zip(IDS, json.loads(run.stdout), strict=True):
        assert r["element"] and r["methods"] == METHODS, gid
        assert r["steps"] == r["expected"], gid
        assert r["stepCount"] == manifest(gid)["stepCount"] == 1
        assert r["nonRealtime"] == 400, "supportsNonRealTime is false, so non-realtime loads are refused"
        assert r["unknownCustom"] == 400


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("path", ["graphics/*/graphic.mjs", "renderer/*.mjs"])
def test_modules_parse(path):
    for f in sorted(GRAPHICS_DIR.parent.glob(path)):
        run = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True, timeout=30, check=False)
        assert run.returncode == 0, f"{f}: {run.stderr}"
