"""Collect real Metrics -> Logs -> Traces evidence; never create challenge.json.

Run --scenario tool_fail for practice, or --challenge with the original Coach file.
The API must already run with .env and network access. Restores the injected flag.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.challenge import load_challenge
from scripts.dashboard import summarize


def now():
    return datetime.now(timezone.utc).isoformat()


def read_logs():
    path = ROOT / 'data/logs.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--scenario', choices=['rag_slow', 'tool_fail', 'cost_spike'])
    mode.add_argument('--challenge', action='store_true')
    parser.add_argument('--verify-only', action='store_true', help='Retry Cloud verification of existing evidence without new traffic')
    args = parser.parse_args()
    challenge = load_challenge(ROOT/'config/challenge.json') if args.challenge else None
    prefix = 'cp3-challenge' if challenge else f'cp3-practice-{args.scenario}'
    output = ROOT / 'submission/evidence' / f'{prefix}.json'
    if args.verify_only:
        verify(output)
        return
    if output.exists():
        raise RuntimeError(f'{output.name} already exists; preserve previous evidence before rerunning')
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=30) as api:
        health = api.get('/health').json()
        if not health.get('ok') or any(health['incidents'].values()):
            raise RuntimeError('Start with a healthy API and all incident flags disabled')
        record = {'mode':'official' if challenge else 'practice',
                  'challenge_id':challenge.challenge_id if challenge else None,
                  'started_at':now(), 'phases':[]}

        def save():
            output.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')

        def command(script, *arguments):
            result = subprocess.run([sys.executable, f'scripts/{script}.py', *arguments], cwd=ROOT,
                                    capture_output=True, text=True, encoding='utf-8')
            if result.returncode:
                raise RuntimeError(f'{script} failed: {result.stderr}')

        def phase(name):
            before = len(read_logs())
            started = now()
            arguments = ['--challenge'] if challenge else []
            command('load_test', *arguments, '--concurrency', '5')
            rows = read_logs()[before:]
            metrics = summarize(rows)
            metrics = {k:None if isinstance(v,float) and math.isnan(v) else v for k,v in metrics.items()}
            # First quantify the symptom, then select a representative log line.
            terminal = [(before+i+1,r) for i,r in enumerate(rows) if r.get('event') in ('request_failed','response_sent')]
            if not terminal or len(terminal) != metrics['requests']:
                raise RuntimeError('Missing terminal request logs or workload did not finish')
            if metrics['error_rate_pct']:
                selected = next(pair for pair in terminal if pair[1]['event'] == 'request_failed')
            elif name == 'incident' and metrics['cost'] > record['phases'][0]['metrics']['cost'] * 1.5:
                selected = max(terminal, key=lambda pair:pair[1].get('cost_usd',0))
            else:
                selected = max(terminal, key=lambda pair:pair[1].get('latency_ms',0))
            entry = {'name':name,'started_at':started,'ended_at':now(),'metrics':metrics,
                     'correlation_ids':[r['correlation_id'] for _,r in terminal],
                     'selected_log_line':selected[0], 'selected_log':selected[1]}
            record['phases'].append(entry)
            save()
            print(f"{name}: requests={metrics['requests']}, errors={metrics['error_rate_pct']}%, retrieval={metrics['tool_success_rate_pct']}%, p95={metrics['p95']}ms",flush=True)

        scenario_args = ['--scenario', args.scenario] if args.scenario else []
        phase('baseline')
        try:
            command('inject_incident', *scenario_args)
            phase('incident')
        finally:
            command('inject_incident', *scenario_args, '--disable')
        phase('recovered')
        record['health_after'] = api.get('/health').json()
        assert not any(record['health_after']['incidents'].values())
        save()

    time.sleep(8)  # allow background exporter to send final batch
    verify(output)


def verify(output):
    record = json.loads(output.read_text(encoding='utf-8'))

    def save():
        output.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')

    settings = dotenv_values(ROOT/'.env')
    with httpx.Client(base_url=settings['LANGFUSE_BASE_URL'],
                      auth=(settings['LANGFUSE_PUBLIC_KEY'],settings['LANGFUSE_SECRET_KEY']),
                      transport=httpx.HTTPTransport(retries=2),timeout=20) as cloud:
        project_response = cloud.get('/api/public/projects')
        project_response.raise_for_status()
        project = project_response.json()['data'][0]
        record['project'] = {k:project[k] for k in ('id','name')}
        params = {'fromStartTime':record['started_at'],'toStartTime':now(),'limit':100,
                  'fields':'core,basic,metadata,usage,prompt,model,io,trace_context'}
        observations=[]
        while True:
            response=cloud.get('/api/public/v2/observations',params=params)
            response.raise_for_status()
            page=response.json()
            observations.extend(page['data'])
            cursor=page.get('meta',{}).get('cursor')
            if not cursor:
                break
            params['cursor']=cursor
        allowed=('id','traceId','parentObservationId','name','type','level','statusMessage',
                 'startTime','endTime','model','usageDetails','costDetails','promptName','promptVersion','input','output')
        for p in record['phases']:
            cid=p['selected_log']['correlation_id']
            matches=[o for o in observations if o.get('metadata',{}).get('correlation_id')==cid]
            root=next(o for o in matches if o['name']=='lab-agent-run')
            assert all(o.get('input') is None and o.get('output') is None for o in matches)
            assert all(o['parentObservationId']==root['id'] for o in matches if o['name']!='lab-agent-run')
            p['trace_id']=root['traceId']
            p['trace_url']=f"{settings['LANGFUSE_BASE_URL']}/project/{project['id']}/traces/{root['traceId']}"
            p['observations']=[{**{k:o.get(k) for k in allowed},'correlation_id':cid} for o in matches]
        # The conclusion is recorded after checking the observations, not inferred from the scenario flag.
        incident=record['phases'][1]
        retrieval=next(o for o in incident['observations'] if o['name']=='retrieval')
        incident['retrieval_duration_ms']=(datetime.fromisoformat(retrieval['endTime'].replace('Z','+00:00'))-
                                            datetime.fromisoformat(retrieval['startTime'].replace('Z','+00:00'))).total_seconds()*1000
        record['verified_at']=now()
        save()
    print(f'Evidence saved: {output}',flush=True)


if __name__=='__main__':
    main()
