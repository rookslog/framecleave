import pytest


def test_atomic_metadata_is_refused_before_growth_and_preserves_old_file(tmp_path):
    from framecleave.storage import atomic_bytes
    from framecleave.tempbudget import temporary_budget, TemporaryBudgetError

    target = tmp_path / 'metadata'
    target.write_bytes(b'old')
    with temporary_budget(5) as budget:
        with pytest.raises(TemporaryBudgetError):
            atomic_bytes(target, b'123456')
        assert budget.peak_bytes <= 5
        assert budget.current_bytes == 0
    assert target.read_bytes() == b'old'
    assert list(tmp_path.iterdir()) == [target]


def test_concurrent_filter_and_metadata_reservations_share_one_limit(tmp_path):
    from framecleave.storage import atomic_bytes
    from framecleave.tempbudget import reserve_temp, temporary_budget, TemporaryBudgetError

    with temporary_budget(10) as budget:
        with reserve_temp(7):
            with pytest.raises(TemporaryBudgetError):
                atomic_bytes(tmp_path / 'refused', b'1234')
            atomic_bytes(tmp_path / 'allowed', b'123')
            assert budget.peak_bytes == 10
        assert budget.current_bytes == 0


def test_streamed_metrics_writer_enforces_high_water_before_disk_growth(tmp_path):
    from framecleave.storage import atomic_write
    from framecleave.tempbudget import temporary_budget, TemporaryBudgetError

    def writer(handle):
        handle.write(b'1234')
        handle.seek(2)
        handle.write(b'5678')

    with temporary_budget(5) as budget:
        with pytest.raises(TemporaryBudgetError):
            atomic_write(tmp_path / 'metrics', writer)
        assert budget.peak_bytes == 4
        assert budget.current_bytes == 0
    assert not list(tmp_path.iterdir())


def test_live_job_lock_is_counted_and_released(tmp_path):
    from framecleave.storage import JobDirectory
    from framecleave.tempbudget import temporary_budget

    with temporary_budget(1024) as budget:
        with JobDirectory(tmp_path / 'job') as root:
            assert budget.current_bytes == (root / '.lock').stat().st_size
            assert budget.current_bytes > 0
        assert budget.current_bytes == 0


def test_partial_at_writer_ceiling_plus_live_lock_fits_actual_filesystem_bytes(source_video, tmp_path, monkeypatch):
    from framecleave.media import MediaError
    from framecleave.review_copy import ReviewCopySession
    from framecleave.storage import JobDirectory
    from framecleave.tempbudget import temporary_budget
    from test_export import timeline_from_source

    info, timeline = timeline_from_source(source_video)
    ceiling = source_video.stat().st_size * 3 // 2
    with temporary_budget(ceiling), JobDirectory(tmp_path / 'job') as root:
        session = ReviewCopySession(info, timeline)

        def fill_to_ceiling(command, partial):
            partial.write_bytes(b'x' * session.max_temp_bytes)
            actual = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
            assert actual <= ceiling
            raise MediaError('controlled stop before inventory probing')

        monkeypatch.setattr(session, '_run_copy', fill_to_ceiling)
        with pytest.raises(MediaError, match='controlled stop'):
            session.export(timeline.scenes([7])[0], root / 'scene.mp4')
        assert not list(root.glob('*.partial'))
