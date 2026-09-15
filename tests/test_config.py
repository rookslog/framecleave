import pytest


def test_unknown_config_key_is_error(tmp_path):
    from framecleave.config import load_config
    p = tmp_path / 'x.toml'; p.write_text('[framecleave]\nthrehsold=1\n')
    with pytest.raises(ValueError, match='Unknown'):
        load_config(p)


def test_config_fingerprint_is_stable():
    from framecleave.config import Config
    assert Config().fingerprint() == Config().fingerprint()
    assert Config(threads=1).fingerprint() != Config(threads=2).fingerprint()


def test_config_has_bounded_resources():
    from framecleave.config import Config
    with pytest.raises(ValueError):
        Config(threads=0)


def test_toml_overrides_defaults(tmp_path):
    from framecleave.config import load_config
    p = tmp_path / 'c.toml'; p.write_text('[framecleave]\nthreads=1\n')
    assert load_config(p).threads == 1
