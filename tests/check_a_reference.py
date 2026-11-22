"""Offline checks: full-source A evidence, <=30s reference, DSH plugin."""
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--comfy-root', required=True, type=Path)
args = parser.parse_args()
PROJECT = Path(__file__).resolve().parents[1]


def main():
    root = Path(tempfile.mkdtemp(prefix='a-reference-30s-'))
    os.environ['DSH_BRIDGE_DATA_DIR'] = str(root / 'DSH-results')
    sys.path.insert(0, str(args.comfy_root))
    sys.argv = [sys.argv[0]]
    from comfy_api.latest import InputImpl
    from comfy_execution.graph_utils import ExecutionBlocker
    import av
    from PIL import Image
    ffmpeg = PROJECT / 'vendor/ffmpeg/windows-x64/ffmpeg.exe'
    long_file, short_file, fractional = root / 'long-tail.mp4', root / 'short.mp4', root / 'fractional-audio.mp4'
    def generate(args):
        subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', *args],
                       check=True, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    generate(['-f', 'lavfi', '-i', 'color=c=red:s=128x128:r=10:d=30', '-f', 'lavfi', '-i',
              'color=c=blue:s=128x128:r=10:d=1.5', '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]',
              '-map', '[v]', '-c:v', 'libx264', '-threads', '1', str(long_file)])
    generate(['-f', 'lavfi', '-i', 'color=c=green:s=128x128:r=10:d=3', '-c:v', 'libx264', '-threads', '1', str(short_file)])
    generate(['-f', 'lavfi', '-i', 'color=c=red:s=128x128:r=30000/1001:d=31.5', '-f', 'lavfi', '-i',
              'sine=frequency=440:duration=31.5', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac', str(fractional)])
    report = {'remote_model_requests': 0, 'root': str(root), 'plugins': {}}
    original_hash = hashlib.sha256(long_file.read_bytes()).hexdigest()
    for label, plugin, ns, prefix in [
        ('DSH', PROJECT, 'dsh_bridge', 'dsh'),
    ]:
        name = 'a_trim_test_' + label
        package = types.ModuleType(name); package.__path__ = [str(plugin)];sys.modules[name] = package
        nodepkg = types.ModuleType(name + '.nodes');nodepkg.__path__ = [str(plugin / 'nodes')];sys.modules[nodepkg.__name__] = nodepkg
        module = importlib.import_module(name + '.nodes.' + prefix + '_video_agent')
        bridge = importlib.import_module(name + '.' + ns + '.bridge')
        media = importlib.import_module(name + '.' + ns + '.media_tools')
        helper = importlib.import_module(name + '.' + ns + '.a_reference_video')
        route = importlib.import_module(name + '.' + ns + '.duration_routing')
        calls = []
        def ask(instance, session, *args, **kwargs):
            if 'chain-a-final-review' in session:
                review_evidence = instance.cfg['video_media_evidence']
                assert '31.' in review_evidence and 'full source prompt including tail' in review_evidence
                assert instance.cfg['video_system_prompt'] == module.A_REVIEW_RULES
                calls.append({'review_uses_full_source': True})
                return {'text': json.dumps({'status': 'approved', 'checks': {'full source': True},
                                           'issues': [], 'edits': []}), 'events': [], 'usage': {}}
            source = Path(instance.cfg['workspace']) / 'source-video.mp4'
            info = media.MediaTools(source, source.parent / 'media-analysis').info()
            assert info['duration_seconds'] > 30
            evidence = instance.cfg['video_media_evidence']
            assert '提示词描述' in evidence and '31.' in evidence
            assert instance.cfg['video_system_prompt'] == 'UNCHANGED_A_RULES'
            calls.append({'analysis_duration': info['duration_seconds'], 'system_rules_preserved': True})
            return {'text': 'full source prompt including tail', 'events': [], 'usage': {}, 'finish_reason': 'completed'}
        class Node(module.__dict__[prefix.upper() + '_FullVideoAgent']):
            hidden = types.SimpleNamespace(unique_id='trim-check-' + label)
        source = InputImpl.VideoFromFile(str(long_file))
        gen = Node.iter_chain_a(source, route.route_duration(source.get_duration()), 'offline-placeholder',
                               'http://127.0.0.1:9/v1', 'offline', 'keep all source information',
                               'UNCHANGED_A_RULES', 120, 32768, str(root / 'missing-asr'),
                               'openai-completions', 'high', True, None, (None,) * 10, publish_video=True)
        with patch.object(bridge.Bridge, 'ask', ask):
            first = next(gen)
            reference = first[3]
            assert reference.get_duration() <= 30
            assert all(isinstance(v, ExecutionBlocker) for v in first[4:])
            stage_record = json.loads(first[1])['video_outputs']
            assert stage_record['trimmed'] and stage_record['analysis_duration_seconds'] > 30
            # The generator retains its full temporary source and evidence while yielding.
            frame = gen.gi_frame
            output = frame.f_locals['output']
            preparation = json.loads((output / 'preparation.json').read_text(encoding='utf-8'))
            prepared_times = [t for sheet in preparation['sheets'] for t in sheet['actual_times']]
            assert max(prepared_times) > 30, 'tail frames were dropped before reverse'
            transcript = json.loads((output / 'transcript.json').read_text(encoding='utf-8'))
            # Read the staged full source directly to confirm its tail has the blue event.
            frames = []
            with av.open(str(output.parent / 'source-video.mp4')) as container:
                for f in container.decode(video=0):
                    if float(f.pts * f.time_base) >= 30.5:
                        frames.append(f.to_ndarray(format='rgb24').mean(axis=(0, 1)))
            assert frames and frames[-1][2] > frames[-1][0]
            try:
                next(gen)
                raise AssertionError('generator did not finish')
            except StopIteration as done:
                final = done.value
            assert final[0] == 'full source prompt including tail'
            assert json.loads(final[1])['video_outputs']['analysis_duration_seconds'] > 30
        # Output must survive the workflow TemporaryDirectory cleanup and contain no blue tail.
        buffer = io.BytesIO();reference.save_to(buffer)
        with av.open(io.BytesIO(buffer.getvalue())) as container:
            decoded = list(container.decode(video=0))
            assert len(decoded) == 300
            assert all(f.to_ndarray(format='rgb24').mean(axis=(0, 1))[0] > 200 for f in decoded)
        short = InputImpl.VideoFromFile(str(short_file))
        unchanged, short_record = helper.prepare_a_reference(short, root, {'duration_seconds': 3})
        assert unchanged is short and not short_record['trimmed']
        audio_workspace = root / (label + '-fractional');audio_workspace.mkdir()
        shutil.copy2(fractional, audio_workspace / 'source-video.mp4')
        audio_output = audio_workspace / 'analysis';audio_output.mkdir()
        info = media.MediaTools(audio_workspace / 'source-video.mp4', audio_output).info()
        audio_reference, audio_record = helper.prepare_a_reference(InputImpl.VideoFromFile(str(fractional)), audio_output, info)
        assert audio_record['actual_duration_seconds'] <= 30
        b = io.BytesIO();audio_reference.save_to(b)
        with av.open(io.BytesIO(b.getvalue())) as container:
            assert len(container.streams.audio) == 1
        assert route.route_duration(31.999)['chain'] == 'A' and route.route_duration(32)['chain'] == 'B'
        report['plugins'][label] = {'full_analysis_duration': stage_record['analysis_duration_seconds'],
                                   'max_prepared_frame_time': max(prepared_times), 'reference_duration': reference.get_duration(),
                                   'exported_frames': 300, 'tail_event_remains_in_analysis': True,
                                   'tail_event_removed_from_reference': True, 'short_video_unchanged': True,
                                   'fractional_fps_audio_reference_duration': audio_record['actual_duration_seconds'],
                                   'audio_preserved': True, 'original_source_unchanged': hashlib.sha256(long_file.read_bytes()).hexdigest() == original_hash,
                                   'reverse_called_once': len([c for c in calls if 'analysis_duration' in c]) == 1,
                                   'review_called_once_with_full_source': len([c for c in calls if 'review_uses_full_source' in c]) == 1,
                                   'system_rules_unchanged': True}
        assert all(v is not False for v in report['plugins'][label].values())
    report['success'] = True
    target = root / 'verification.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()