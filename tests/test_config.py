import pytest

from app.config import load_config


def test_defaults():
    cfg = load_config({})
    assert cfg.data_dir.as_posix() == "/data"
    assert (cfg.hr_max, cfg.hr_rest, cfg.lthr, cfg.sex) == (190.0, 50.0, 170.0, "m")


def test_reads_env(tmp_path):
    cfg = load_config({"DATA_DIR": str(tmp_path), "HR_MAX": "195", "HR_REST": "48",
                       "LTHR": "172", "SEX": "F"})
    assert cfg.data_dir == tmp_path
    assert cfg.db_path == tmp_path / "trend.db"
    assert (cfg.hr_max, cfg.hr_rest, cfg.lthr, cfg.sex) == (195.0, 48.0, 172.0, "f")


@pytest.mark.parametrize("env, message", [
    ({"HR_MAX": "abc"}, "HR_MAX"),
    ({"SEX": "x"}, "SEX"),
    ({"LTHR": "200"}, "LTHR"),
])
def test_invalid_values(env, message):
    with pytest.raises(ValueError, match=message):
        load_config(env)


def test_ensure_dirs(config):
    config.ensure_dirs()
    for d in (config.fit_dir, config.series_dir, config.strava_dir, config.garmin_tokens_dir):
        assert d.is_dir()
