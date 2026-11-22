"""A review uses the exact user rules, applies verified edits and keeps drafts."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge import a_review


@pytest.mark.parametrize('mode', ['approved', 'corrected', 'invalid', 'blocked', 'wrong-index'])
def test_isolated_review_custom_rules_and_failure_artifacts(monkeypatch, tmp_path, mode):
    custom_rules = '  用户的审核规则\n只检查自定义范围。\n'
    draft = 'alpha beta full source'
    decision = {'status': 'approved', 'checks': {'用户检查项': True}, 'issues': [], 'edits': []}
    if mode == 'corrected':
        decision.update(status='corrected', edits=[
            {'segment_index': 1, 'old': 'alpha', 'new': 'alpha', 'reason': '保持原文'},
            {'segment_index': 1, 'old': 'beta', 'new': 'BETA', 'reason': '素材证据'}])
    if mode == 'blocked':
        decision.update(status='blocked', checks={'用户检查项': False}, issues=['明确矛盾'])
    if mode == 'wrong-index':
        decision.update(status='corrected', edits=[
            {'segment_index': 2, 'old': 'beta', 'new': 'BETA', 'reason': '错误段号'}])
    calls = []
    class Bridge:
        cfg = {}
        def session_id(self, name):
            assert name == 'chain-a-final-review'
            return name
        def ask(self, session, task, images, **kwargs):
            assert self.cfg['video_system_prompt'] == custom_rules
            assert '原始A规则' in self.cfg['video_media_evidence']
            assert '完整原片尾部31.5秒' in self.cfg['video_media_evidence']
            assert draft in self.cfg['video_media_evidence']
            assert images == ['full-source-sheet']
            calls.append(session)
            return {'text': 'invalid json' if mode == 'invalid' else json.dumps(decision),
                    'usage': {'output_tokens': 20}}
    @contextmanager
    def workflow(**kwargs):
        assert kwargs['model'] == 'custom-review-model'
        assert kwargs['api_key'] == 'local-placeholder'
        yield Bridge()
    monkeypatch.setattr(a_review, 'workflow_bridge', workflow)
    speed = SimpleNamespace(phase='reverse', run_id='test-run')
    params = dict(draft=draft, requirement='用户要求', reverse_rules='原始A规则', review_rules=custom_rules,
        media_text='完整原片尾部31.5秒', analysis_evidence={}, images=['full-source-sheet'],
        reviewer=dict(model='custom-review-model', api_key='local-placeholder', base_url='http://127.0.0.1:9/v1',
                      api_protocol='openai-completions'), ai_mode='自定义', speed=speed,
        audit_dir=tmp_path, result_dir=tmp_path / 'results', timeout_s=20, max_tokens=2048,
        reasoning_effort='high', stream_usage=True)
    if mode in ['invalid', 'blocked', 'wrong-index']:
        with pytest.raises(RuntimeError, match='A草稿与审核记录保留'):
            a_review.final_review(**params)
        assert not (tmp_path / 'results/prompts.txt').exists()
        assert (tmp_path / 'results/review-error.json').exists()
    else:
        result, record = a_review.final_review(**params)
        assert result == ('alpha BETA full source' if mode == 'corrected' else draft)
        assert record['applied_edits'] == (1 if mode == 'corrected' else 0)
        assert record['usage'] == {'output_tokens': 20}
        assert record['model'] == 'custom-review-model'
    assert speed.phase == 'review' and len(calls) == 1
    assert (tmp_path / 'results/draft-prompts.txt').read_text(encoding='utf-8') == draft
    assert (tmp_path / 'results/review-response.json').exists()
