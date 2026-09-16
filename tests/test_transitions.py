import numpy as np
import pytest


def _card(count=10):
    return np.full((count, 32, 48, 3), 128, dtype=np.uint8)


def _classify(frames, **changes):
    from framecleave.transitions import classify_transition

    values = {'before': np.full((32, 48, 3), [200, 20, 20], dtype=np.uint8),
              'after': np.full((32, 48, 3), [20, 20, 200], dtype=np.uint8),
              'audio_activity': 0.0}
    values.update(changes)
    return classify_transition(frames, source_range=(100, 100 + len(frames)), **values)


def test_stable_neutral_card_with_two_sided_context_is_evidence_only_candidate():
    result = _classify(_card())
    assert result.classification == 'transition_candidate'
    assert result.source_range == (100, 110)
    assert result.evidence['frames_examined'] == 10
    assert result.evidence['template_scope'] == 'generic-neutral-card-v1'
    assert 'action' not in result.to_dict()


def test_short_dark_textured_scene_is_not_a_transition_candidate():
    frames = np.random.default_rng(42).integers(0, 40, (10, 32, 48, 3), dtype=np.uint8)
    assert _classify(frames).classification == 'ordinary'


@pytest.mark.parametrize('audio_activity', [.01, None])
def test_card_with_active_or_unknown_audio_is_ambiguous(audio_activity):
    assert _classify(_card(), audio_activity=audio_activity).classification == 'ambiguous'


@pytest.mark.parametrize('missing', ['before', 'after'])
def test_first_or_last_card_requires_review(missing):
    assert _classify(_card(), **{missing: None}).classification == 'ambiguous'


def test_fades_flashes_overlays_and_changing_frames_are_not_clear_candidates():
    fade = np.stack([np.full((32, 48, 3), 100 + number * 2, dtype=np.uint8) for number in range(10)])
    overlay = _card()
    overlay[:, 10:12, 10:20] = 0
    changing = _card()
    changing[5, :10] = 220
    for frames in [fade, _card(1), overlay, changing]:
        assert _classify(frames).classification != 'transition_candidate'


def test_short_duration_alone_never_creates_an_omission_decision():
    result = _classify(np.full((10, 32, 48, 3), [20, 150, 200], dtype=np.uint8))
    assert result.classification == 'ordinary'
    assert 'omit' not in str(result.to_dict())


def test_transition_decisions_default_to_keep_and_reject_invalid_overrides():
    from framecleave.transitions import resolve_transition_decisions

    scenes = [{'number': 1, 'transition': {'classification': 'ordinary'}},
              {'number': 2, 'transition': {'classification': 'transition_candidate'}},
              {'number': 3, 'transition': {'classification': 'ambiguous'}}]
    assert resolve_transition_decisions(scenes) == {2: 'keep', 3: 'keep'}
    assert resolve_transition_decisions(scenes, default='collapse', overrides=['2=omit']) == {2: 'omit', 3: 'collapse'}
    for overrides in [['2=omit', '2=keep'], ['1=omit'], ['99=omit'], ['2=delete']]:
        with pytest.raises(ValueError):
            resolve_transition_decisions(scenes, overrides=overrides)
