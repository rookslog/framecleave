from framecleave.model import Timeline
from fractions import Fraction


def test_report_is_local_escaped_and_marks_review(tmp_path):
    from framecleave.report import render_report
    t = Timeline([0, 40, 80], [40, 40, 40], [0], Fraction(1, 1000))
    index = {'source': {'display_name': '<script>alert(1)</script>'}, 'scenes': t.scenes([1]),
             'boundaries': [{'frame': 1, 'decision': 'cut', 'reason': '<edit>', 'evidence': {}},
                            {'frame': 2, 'decision': 'review', 'reason': 'ambiguous', 'evidence': {}}],
             'detector': {'name': 'temporal'}, 'schema_version': 1, 'timeline': t.to_dict()}
    render_report(index, tmp_path)
    text = (tmp_path / 'report.html').read_text()
    assert '<script>' not in text
    assert '&lt;script&gt;' in text
    assert 'Needs review' in text
    assert 'Not included in the proposed split' in text
    assert 'http://' not in text and 'https://' not in text
    assert 'end exclusive' in text


def test_thumbnails_use_exact_ordinals(source_video, tmp_path):
    from framecleave.report import make_thumbnails
    from framecleave.media import probe
    from framecleave.detector import analyze
    from framecleave.config import Config
    import cv2
    info = probe(source_video)
    t = analyze(info, Config()).timeline
    index = {'scenes': t.scenes([7, 8]), 'boundaries': [{'frame': 7, 'decision': 'cut'}], 'timeline': t.to_dict()}
    make_thumbnails(info, index, tmp_path, threads=1)
    assert index['scenes'][1]['thumbnails']['start'] == index['scenes'][1]['thumbnails']['end']
    for scene in index['scenes']:
        for path in scene['thumbnails'].values():
            assert cv2.imread(str(tmp_path / path)) is not None
    assert [p['frame'] for p in index['boundaries'][0]['thumbnails']] == [5, 6, 7, 8]
