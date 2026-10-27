import asyncio

import pytest
from agent_framework import Message

from talkback.hosted import runs
from talkback.hosted.runstore import run_dir


def _msg(text: str) -> Message:
    return Message(role="user", contents=[text])


def test_run_named_in_the_prompt():
    assert runs.run_of([_msg("Run: md-2027\nMatch: A v B")]) == "md-2027"


@pytest.mark.parametrize("text", ["Match: A v B", "Run: ../../etc", "Run: md 2027", "Run: " + "x" * 80])
def test_unusable_run_line_falls_back_to_the_default(text, monkeypatch):
    monkeypatch.setenv("TALKBACK_RUN_ID", "md-2026")
    assert runs.run_of([_msg(text)]) == "md-2026"


def test_scope_makes_the_run_visible_to_tools():
    seen, warmed = [], []

    class Ctx:
        messages = [_msg("Run: md-2030\nMoment: goal")]

    async def call_next():
        seen.append(runs.current())

    asyncio.run(runs.RunScope(warm=warmed.append).process(Ctx(), call_next))
    assert seen == ["md-2030"] and warmed == ["md-2030"]


def test_cache_loads_each_run_once_and_evicts_the_oldest():
    loads = []
    cache = runs.RunCache(lambda r: loads.append(r) or r.upper(), size=2)
    assert [cache.get(r) for r in ("a", "b", "a", "c", "b")] == ["A", "B", "A", "C", "B"]
    assert loads == ["a", "b", "c", "b"]


def test_run_dir_finds_sibling_runs_locally(tmp_path, monkeypatch):
    for name in ("md-2026", "md-2027"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "world.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TALKBACK_RUN_DIR", str(tmp_path / "md-2026"))
    assert run_dir() == tmp_path / "md-2026"
    assert run_dir("md-2027") == tmp_path / "md-2027"
    with pytest.raises(ValueError):
        run_dir("../md-2027")


def _in_run(run: str, body, warm=None) -> None:
    class Ctx:
        messages = [_msg(f"Run: {run}\nMoment: shot at 56'")]

    asyncio.run(runs.RunScope(warm=warm).process(Ctx(), body))


def test_hosted_lab_runs_experiments_on_the_prompts_run():
    from talkback.hosted.lab import remote_tools

    calls = []

    class Backend:
        def __init__(self, run_id):
            self.run_id = run_id

        def run(self, moment_id, match_id, event_id, kind):
            calls.append((self.run_id, match_id))
            return []

    backends = runs.RunCache(Backend)
    (run_experiment,) = remote_tools(backends)

    async def body():
        await run_experiment.func(match_id="MD12-F01", moment_id="M-1", event_id="E-1", experiment="cancel_shot")

    _in_run("md-2028", body, warm=backends.get)
    assert calls == [("md-2028", "MD12-F01")]


def test_hosted_archivist_reads_the_prompts_world():
    from types import SimpleNamespace

    from talkback.hosted.archivist import RunWorld

    world = RunWorld(runs.RunCache(lambda r: SimpleNamespace(run=r)))
    seen = []

    async def body():
        seen.append(world.run)

    _in_run("md-2029", body)
    assert seen == ["md-2029"]


def test_partly_cached_run_still_fetches_missing_matches(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from talkback.hosted import runstore

    monkeypatch.setenv("STORAGE_ACCOUNT_URL", "https://example.blob.core.windows.net")
    root = tmp_path / "md-9"
    (root / "snapshots" / "F01").mkdir(parents=True)
    (root / "snapshots" / "F01" / "30000.pkl.gz").write_bytes(b"x")
    blobs = {"md-9/snapshots/F02/60000.pkl.gz": b"y"}

    class Container:
        def list_blobs(self, name_starts_with):
            return [SimpleNamespace(name=n) for n in blobs if n.startswith(name_starts_with)]

        def download_blob(self, name):
            return SimpleNamespace(readall=lambda: blobs[name])

    monkeypatch.setattr(runstore, "_container", Container)
    store = runstore.snapshot_store(root, "md-9")
    assert store.times("F01") == [30000]
    assert store.times("F02") == [60000]


def test_prewarm_failure_is_logged_not_raised(caplog):
    def load(run_id):
        raise PermissionError("storage access not granted yet")

    with caplog.at_level("WARNING"):
        assert runs.prewarm(runs.RunCache(load), "md-2026") is False
    assert "md-2026" in caplog.text
    assert runs.prewarm(runs.RunCache(str.upper), "md-2026") is True


def test_a_failed_download_leaves_nothing_cached(tmp_path, monkeypatch):
    from talkback.hosted import runstore

    class Container:
        def download_blob(self, name):
            raise ConnectionError("storage unreachable")

    monkeypatch.setattr(runstore, "_container", Container)
    with pytest.raises(ConnectionError):
        runstore._download("https://example.blob.core.windows.net", "md-9", tmp_path, ("world.json",))
    assert list(tmp_path.iterdir()) == []
