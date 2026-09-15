import json
import pytest


def test_job_directory_refuses_unowned_data(tmp_path):
    from framecleave.storage import JobDirectory
    (tmp_path / 'precious.txt').write_text('keep')
    with pytest.raises(FileExistsError):
        with JobDirectory(tmp_path):
            pass
    assert (tmp_path / 'precious.txt').read_text() == 'keep'


def test_live_lock_is_not_stolen_by_resume(tmp_path):
    from framecleave.storage import JobDirectory, atomic_json
    root = tmp_path / 'out'
    with JobDirectory(root):
        atomic_json(root / 'state.json', {'status': 'running'})
        with pytest.raises(FileExistsError):
            with JobDirectory(root, resume=True):
                pass
    assert not (root / '.lock').exists()
    with JobDirectory(root, resume=True):
        assert (root / '.lock').exists()


def test_atomic_json_handles_unicode_and_refuses_nan(tmp_path):
    from framecleave.storage import atomic_json
    path = tmp_path / 'é.json'
    atomic_json(path, {'name': 'résumé'})
    assert json.loads(path.read_text()) == {'name': 'résumé'}
    with pytest.raises(ValueError):
        atomic_json(path, {'n': float('nan')})
    assert json.loads(path.read_text()) == {'name': 'résumé'}
