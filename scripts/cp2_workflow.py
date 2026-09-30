"""Run the explicitly requested CP2 prompt lifecycle and real timed workload.

Mutates day13-chat labels in the configured personal Langfuse project.
Always restores production to baseline and .env label to production.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'submission/evidence'
TEMPLATE = 'Feature={{feature}}\nDocs={{docs}}\nQuestion={{message}}'


def set_label(label):
    path = ROOT / '.env'
    text = path.read_text(encoding='utf-8')
    text, count = re.subn(r'^LANGFUSE_PROMPT_LABEL=.*$', f'LANGFUSE_PROMPT_LABEL={label}', text, flags=re.M)
    if count != 1:
        raise RuntimeError('Expected exactly one LANGFUSE_PROMPT_LABEL in .env')
    path.write_text(text, encoding='utf-8')


def main():
    settings = dotenv_values(ROOT / '.env')
    base = settings['LANGFUSE_BASE_URL']
    cloud = httpx.Client(base_url=base, auth=(settings['LANGFUSE_PUBLIC_KEY'], settings['LANGFUSE_SECRET_KEY']), timeout=30)
    local = httpx.Client(base_url='http://127.0.0.1:8000', timeout=30)
    try:
        local.get('/health', timeout=2)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        pass
    else:
        raise RuntimeError('Port 8000 already serves an API. Stop it before this workflow.')
    def api(method, path, **kwargs):
        response = cloud.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    project = api('GET', '/api/public/projects')['data'][0]
    versions = {}
    for label, text in [('baseline', TEMPLATE), ('candidate', TEMPLATE + '\nKeep the answer concise.')]:
        response = cloud.get('/api/public/v2/prompts/day13-chat', params={'label': label})
        if response.status_code == 404:
            prompt = api('POST', '/api/public/v2/prompts', json={
                'name': 'day13-chat', 'type': 'text', 'prompt': text,
                'labels': [label, 'production'] if label == 'baseline' else [label],
            })
        else:
            response.raise_for_status()
            prompt = response.json()
        if prompt['type'] != 'text' or not all('{{' + x + '}}' in prompt['prompt'] for x in ('feature','docs','message')):
            raise RuntimeError('Existing prompt does not satisfy the CP2 contract')
        versions[label] = prompt['version']
    def production(version):
        return api('PATCH', f'/api/public/v2/prompts/day13-chat/versions/{version}', json={'newLabels': ['production']})

    record = {'project': {'id': project['id'], 'name': project['name']}, 'base_url': base,
              'started_at': datetime.now(timezone.utc).isoformat(), 'versions': versions, 'stages': [], 'batches': []}
    def save():
        (EVIDENCE / '09-10-prompt-lifecycle.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    server = None
    output = (ROOT / 'data/cp2-api.log').open('a', encoding='utf-8')
    def stop():
        nonlocal server
        if server is not None:
            # The SDK exporter runs in the background; allow its 5s batch timer.
            time.sleep(8)
            server.terminate()
            server.wait(timeout=30)
            server = None
    def start(label):
        nonlocal server
        set_label(label)
        env = os.environ.copy()
        env.update({k: v for k, v in dotenv_values(ROOT / '.env').items() if v is not None})
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--env-file', '.env'],
                                  cwd=ROOT, env=env, stdout=output, stderr=output,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(60):
            if server.poll() is not None:
                raise RuntimeError('API failed to start; inspect ignored data/cp2-api.log')
            try:
                health = local.get('/health').json()
                if health.get('ok') and health.get('tracing_enabled'):
                    return
            except (httpx.ConnectError, httpx.ConnectTimeout):
                pass
            time.sleep(.5)
        raise RuntimeError('API health timeout')
    try:
        for stage, label in [('baseline','baseline'), ('candidate','candidate'), ('promote','production'), ('rollback','production')]:
            stop()
            if stage in ('promote', 'rollback'):
                production(versions['candidate' if stage == 'promote' else 'baseline'])
            start(label)
            prompt = api('GET', '/api/public/v2/prompts/day13-chat', params={'label':label})
            response = local.post('/chat', json={'user_id':'cp2-student','session_id':f'cp2-{stage}', 'feature':'qa', 'message':'Explain monitoring using metrics logs and traces.'})
            response.raise_for_status()
            record['stages'].append({'stage':stage, 'label':label, 'version':prompt['version'], 'labels':prompt['labels'],
                                     'correlation_id':response.json()['correlation_id'], 'tokens_in':response.json()['tokens_in'],
                                     'at':datetime.now(timezone.utc).isoformat()})
            save()
            print(f"{stage}: version={prompt['version']} correlation_id={response.json()['correlation_id']}", flush=True)
        # Eleven real batches, spaced one minute apart. No fabricated timestamps.
        for index in range(11):
            began = time.monotonic()
            run = subprocess.run([sys.executable, 'scripts/load_test.py'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
            if run.returncode or run.stdout.count('[200]') != 10:
                raise RuntimeError('Load test did not return 10 successful requests')
            ids = re.findall(r'req-[0-9a-f]{8}', run.stdout)
            record['batches'].append({'index':index, 'at':datetime.now(timezone.utc).isoformat(), 'correlation_ids':ids})
            save()
            print(f'Workload batch {index + 1}/11: {len(ids)} successful requests', flush=True)
            if index < 10:
                time.sleep(max(0, 60 - (time.monotonic() - began)))
    finally:
        try:
            stop()
        finally:
            try:
                production(versions['baseline'])
            finally:
                set_label('production')
                record['finished_at'] = datetime.now(timezone.utc).isoformat()
                save()
                output.close()
                cloud.close()
                local.close()


if __name__ == '__main__':
    main()
