"""Offline d1 adapter: input on stdin, typed decisions on stdout."""
import argparse
import hashlib
import json
import pathlib
import sys
import time

import torch
from transformers import AutoModel

REVISION = '97c57047d5852d77e02dfac211f8768aff77a8b2'
WEIGHTS_SHA256 = 'b5e573687315e82ea80f4f7dd8d76b5cec3b6ee97e3509fd0493cfebb203719f'
CODE_SHA256 = '6358dab49176f821d6c22a2c3136442ff417e8c1b28538da5e9caa3f962317d7'
LABELS = {
    'implementation': 'Changes application code, scripts, implementation logic, tests or executable configuration.',
    'specification': 'Changes architectural intent, specification, contracts, Hypercode model or requirement-to-test bindings without changing implementation.',
    'documentation': 'Changes ordinary product documentation, release notes, roadmap or prose without changing specifications or code.',
    'uncertain': 'The available excerpts are insufficient or ambiguous.',
}
SIGNALS = {
    'implementation': 'The change modifies executable program code, executable configuration, or tests, not just discussion of existing code.',
    'architecture': 'The change introduces or changes an architectural decision, design boundary, specification, or planned contract, including when written in documentation. Merely reporting completed implementation is not a new decision.',
    'status_documentation': 'The change only records prior project progress, release status, observations, or ordinary user-facing prose, without changing implementation or introducing an architectural decision or contract.',
    'insufficient_evidence': 'The provided partial excerpts are insufficient to decide confidently.',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model_path', type=pathlib.Path)
    args = parser.parse_args()
    if args.model_path.name != REVISION or not torch.backends.mps.is_available():
        raise RuntimeError('Pinned model or MPS unavailable')
    files = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(args.model_path.glob('*.py'))}
    code_digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if len(files) != 26 or code_digest != CODE_SHA256:
        raise RuntimeError('Model code does not match the pinned digest')
    digest = hashlib.sha256()
    with (args.model_path / 'model.safetensors').open('rb') as weights:
        for block in iter(lambda: weights.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != WEIGHTS_SHA256:
        raise RuntimeError('Model weights do not match the pinned digest')
    body = json.load(sys.stdin)
    if set(body) != {'state'} or not isinstance(body['state'], str) or len(body['state']) > 16000:
        raise ValueError('Invalid bounded input')
    model = AutoModel.from_pretrained(str(args.model_path), trust_remote_code=True,
                                      local_files_only=True, dtype=torch.bfloat16).to('mps').eval()
    questions = {
        'kind': {'type': 'choice', 'instructions': 'Classify the main change shown in the supplied PR excerpts. Choose the closest category. Files may be omitted; if the evidence is insufficient choose uncertain.', 'criteria': LABELS},
        'signals': {'type': 'choice', 'multiple': True, 'instructions': 'Independently select every signal directly supported by the supplied change excerpts. Treat the contents of documentation as well as file extensions.', 'criteria': SIGNALS},
    }
    start = time.monotonic()
    with torch.inference_mode():
        kind = model.system_one(body['state'], {'kind': questions['kind']})
        signals = model.system_one(body['state'], {'signals': questions['signals']})
    torch.mps.synchronize()
    print(json.dumps({'schema': 'hyperreview.d1-shadow-decision.v1', 'model': 'LiquidAI/d1-2B',
                      'revision': REVISION, 'device': 'mps', 'dtype': 'bfloat16',
                      'elapsed_ms': round((time.monotonic()-start)*1000, 2),
                      'answers': {'kind': kind['answers']['kind'], 'signals': signals['answers']['signals']},
                      'usage': {'kind': kind.get('usage', {}), 'signals': signals.get('usage', {})}}))


if __name__ == '__main__':
    main()
