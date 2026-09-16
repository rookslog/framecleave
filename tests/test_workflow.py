import json
import pytest


class CollectingSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self, result=None):
        pass


def test_dry_run_has_index_report_and_no_clips(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    from framecleave.model import read_index
    out = tmp_path / 'review'
    result = process_video(source_video, out, Config(), dry_run=True, cuts=[7, 47])
    assert result['status'] == 'inspected'
    index = read_index(out / 'scene-index.json')
    assert [s['start_frame'] for s in index['scenes']] == [0, 7, 47]
    assert (out / 'report.html').is_file()
    assert len(list((out / 'thumbnails').glob('*.jpg'))) > 3
    assert not (out / 'scenes').exists()
    assert not (out / '.lock').exists()


def test_workflow_emits_analysis_report_and_terminal_lifecycle(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config

    sink = CollectingSink()
    process_video(source_video, tmp_path / 'review', Config(), dry_run=True, cuts=[7, 47],
                  progress=sink, job_id='job-1')
    names = [event.event for event in sink.events]
    assert names[0] == 'job_started'
    assert {'probing_started', 'analyzing_started', 'boundaries_detected',
            'report_started', 'report_finished'} <= set(names)
    assert names[-1] == 'job_finished'
    assert all(event.job_id == 'job-1' for event in sink.events)


def test_split_resume_and_tamper_detection(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    out = tmp_path / 'résumé job'
    first = process_video(source_video, out, Config(), cuts=[7,47])
    assert first['status'] == 'complete'
    assert first['exported'] == 3
    second = process_video(source_video, out, Config(), cuts=[7,47], resume=True)
    assert second['skipped_verified'] == 3
    index = json.loads((out / 'scene-index.json').read_text())
    target = out / index['scenes'][1]['output_file']
    with target.open('ab') as handle:
        handle.write(b'corruption')
    with pytest.raises(ValueError, match='digest'):
        process_video(source_video, out, Config(), cuts=[7,47], resume=True)


def test_resume_rejects_changed_config(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    out = tmp_path / 'out'
    process_video(source_video, out, Config(), dry_run=True, cuts=[7])
    with pytest.raises(ValueError, match='configuration'):
        process_video(source_video, out, Config(threads=1), dry_run=True, cuts=[7], resume=True)


def test_inspection_can_be_promoted_to_export(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    out = tmp_path / 'out'
    process_video(source_video, out, Config(), dry_run=True, cuts=[7])
    result = process_video(source_video, out, Config(), resume=True, cuts=[7])
    assert result['exported'] == 2


def test_resume_rejects_an_edited_but_valid_segmentation(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    from framecleave.model import Timeline
    out = tmp_path / 'review'
    process_video(source_video, out, Config(), dry_run=True, cuts=[7, 47])
    path = out / 'scene-index.json'
    index = json.loads(path.read_text())
    timeline = Timeline.from_dict(index['timeline'])
    index['scenes'] = timeline.scenes([8, 47])
    index['boundaries'][0].update(frame=8, pts=timeline.pts[8])
    path.write_text(json.dumps(index))
    with pytest.raises(ValueError, match='segmentation'):
        process_video(source_video, out, Config(), dry_run=True, cuts=[7, 47], resume=True)


def test_resume_requires_unchanged_certificate(source_video, tmp_path):
    from framecleave.workflow import process_video
    from framecleave.config import Config
    out = tmp_path / 'export'
    process_video(source_video, out, Config(), cuts=[7, 47])
    certificate = out / 'certificates/0001.json'
    certificate.write_text('{}')
    with pytest.raises(ValueError, match='certificate'):
        process_video(source_video, out, Config(), cuts=[7, 47], resume=True)


def test_resume_rejects_a_changed_compact_profile(source_video, tmp_path):
    from framecleave.config import Config
    from framecleave.policy import ExportPolicy
    from framecleave.workflow import process_video

    out = tmp_path / 'compact-review'
    process_video(source_video, out, Config(), dry_run=True, cuts=[7], mode='compact',
                  policy=ExportPolicy.compact(crf=16))
    with pytest.raises(ValueError, match='export mode changed'):
        process_video(source_video, out, Config(), dry_run=True, cuts=[7], mode='compact', resume=True,
                      policy=ExportPolicy.compact(crf=20))


def test_compact_verification_uses_certified_encoder_settings_not_decode_threads(integer_audio_video, tmp_path):
    from framecleave.config import Config
    from framecleave.workflow import process_video, verify_job

    out = tmp_path / 'compact-job'
    process_video(integer_audio_video, out, Config(threads=1), cuts=[7, 47], mode='compact')
    result = verify_job(integer_audio_video, out / 'scene-index.json', threads=2)
    assert result['verified'] is True
    assert result['policy']['video']['encoder_threads'] == 1
    assert result['pixel_equality'] == 'not_applicable'


def test_compact_verification_refuses_a_different_reference_encoder_build(source_video, tmp_path):
    from framecleave.config import Config
    from framecleave.workflow import process_video, verify_job

    out = tmp_path / 'compact-build'
    process_video(source_video, out, Config(threads=1), cuts=[7], mode='compact')
    certificate = out / 'certificates/0001.json'
    value = json.loads(certificate.read_text())
    value['video']['reference_encoder_build'] = 'different-encoder-build'
    certificate.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='encoder build'):
        verify_job(source_video, out / 'scene-index.json')


def test_compact_stream_copy_is_reverified_under_the_exact_copy_contract(tmp_path):
    import subprocess
    from framecleave.config import Config
    from framecleave.workflow import process_video, verify_job

    source = tmp_path / 'intra.mov'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=128x96:rate=30:duration=1', '-c:v', 'libx264',
                    '-threads', '1', '-g', '1', '-bf', '0', str(source)], check=True)
    out = tmp_path / 'copy-job'
    process_video(source, out, Config(threads=1), cuts=[7, 27], mode='compact')
    certificate = json.loads((out / 'certificates/0002.json').read_text())
    assert certificate['method'] == 'stream-copy-video'
    result = verify_job(source, out / 'scene-index.json')
    assert result['verified'] is True
    assert result['scenes'][1]['video']['pixel_equality'] == 'equal'


def test_workflow_annotates_every_gray_card_frame_without_changing_partition(tmp_path):
    import subprocess
    from framecleave.config import Config
    from framecleave.workflow import process_video

    source = tmp_path / 'card.mov'
    command = ['ffmpeg', '-v', 'error']
    for color in ['red', '0x808080', 'blue']:
        command += ['-f', 'lavfi', '-i', f'color=c={color}:size=160x120:rate=30:duration=1']
    graph = ('[0:v]trim=end_frame=20,setpts=PTS-STARTPTS[a];'
             '[1:v]trim=end_frame=10,setpts=PTS-STARTPTS[b];'
             '[2:v]trim=end_frame=20,setpts=PTS-STARTPTS[c];[a][b][c]concat=n=3:v=1:a=0[v]')
    subprocess.run(command + ['-filter_complex', graph, '-map', '[v]', '-c:v', 'libx264',
                              '-threads', '1', '-bf', '0', str(source)], check=True)
    out = tmp_path / 'review'
    process_video(source, out, Config(threads=1), cuts=[20, 30], dry_run=True)
    index = json.loads((out / 'scene-index.json').read_text())
    assert [scene['start_frame'] for scene in index['scenes']] == [0, 20, 30]
    annotation = index['scenes'][1]['transition']
    assert annotation['classification'] == 'transition_candidate'
    assert annotation['evidence']['frames_examined'] == 10
    assert annotation['source_range'] == [20, 30]
    assert not (out / 'scenes').exists()


def test_workflow_records_audio_activity_for_short_scene_evidence(source_video, tmp_path):
    from framecleave.config import Config
    from framecleave.workflow import process_video

    out = tmp_path / 'audio-review'
    process_video(source_video, out, Config(threads=1), cuts=[7], dry_run=True)
    index = json.loads((out / 'scene-index.json').read_text())
    assert index['scenes'][0]['transition']['evidence']['audio_rms_peak'] > 0


def test_resume_rejects_edited_transition_annotations(source_video, tmp_path):
    from framecleave.config import Config
    from framecleave.workflow import process_video

    out = tmp_path / 'transition-integrity'
    process_video(source_video, out, Config(threads=1), cuts=[7], dry_run=True)
    path = out / 'scene-index.json'
    value = json.loads(path.read_text())
    value['scenes'][0]['transition']['classification'] = 'transition_candidate'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='transition annotation'):
        process_video(source_video, out, Config(threads=1), cuts=[7], dry_run=True, resume=True)
