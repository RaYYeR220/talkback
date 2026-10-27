import pytest

from talkback.world.matchday import prepare_matchday, run_matchday_offline


@pytest.fixture(scope="session")
def run_dir(tmp_path_factory):
    return run_matchday_offline(prepare_matchday(2026), tmp_path_factory.mktemp("ev") / "run", snapshots=False)
