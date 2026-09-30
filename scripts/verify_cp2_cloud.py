"""Read Langfuse v2 observations, validate CP2, export only safe evidence fields."""
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'submission/evidence'


def main():
    settings = dotenv_values(ROOT / '.env')
    run = json.loads((EVIDENCE / '09-10-prompt-lifecycle.json').read_text(encoding='utf-8'))
    expected = {s['correlation_id'] for s in run['stages']}
    expected.update(cid for b in run['batches'] for cid in b['correlation_ids'])
    params = {'fromStartTime': run['started_at'], 'toStartTime': datetime.now(timezone.utc).isoformat(),
              'limit': 100, 'fields': 'core,basic,usage,prompt,metadata,model,io,trace_context'}
    observations = []
    with httpx.Client(base_url=settings['LANGFUSE_BASE_URL'],
                      auth=(settings['LANGFUSE_PUBLIC_KEY'], settings['LANGFUSE_SECRET_KEY']), timeout=30) as client:
        while True:
            response = client.get('/api/public/v2/observations', params=params)
            response.raise_for_status()
            page = response.json()
            observations.extend(page['data'])
            cursor = page.get('meta', {}).get('cursor')
            if not cursor:
                break
            params['cursor'] = cursor
        prompts = []
        for version in sorted(set(run['versions'].values())):
            response = client.get('/api/public/v2/prompts/day13-chat', params={'version':version})
            response.raise_for_status()
            p = response.json()
            prompts.append({k:p[k] for k in ('name','version','labels','type','prompt')})
    groups = defaultdict(list)
    for observation in observations:
        if observation.get('metadata', {}).get('correlation_id') in expected:
            groups[observation['traceId']].append(observation)
    safe_traces, verified = [], set()
    fields = ('id','traceId','name','type','parentObservationId','startTime','endTime',
              'model','usageDetails','costDetails','promptName','promptVersion','input','output','traceName')
    metadata_fields = ('correlation_id','feature','model','prompt_name','prompt_label','prompt_version','prompt_source','prompt_fetch_error')
    for trace_id, group in groups.items():
        by_name = {o['name']:o for o in group}
        assert set(by_name) == {'lab-agent-run','retrieval','generation'}, trace_id
        root, retrieval, generation = [by_name[n] for n in ('lab-agent-run','retrieval','generation')]
        cid = root['metadata']['correlation_id']
        assert root['parentObservationId'] is None
        assert root['traceName'] == 'day13-agent-request'
        assert retrieval['parentObservationId'] == generation['parentObservationId'] == root['id']
        assert retrieval['type'] in ('RETRIEVER','SPAN') and generation['type'] == 'GENERATION'
        assert generation['model'] == 'claude-sonnet-4-5'
        assert generation['usageDetails']['input'] > 0 and generation['usageDetails']['output'] > 0
        assert generation['costDetails']['total'] > 0
        assert root['metadata']['prompt_source'] == 'langfuse', cid
        assert generation['promptName'] == 'day13-chat'
        assert str(generation['promptVersion']) == str(root['metadata']['prompt_version'])
        assert all(o.get('input') is None and o.get('output') is None for o in group)
        assert all(o['metadata']['correlation_id'] == cid for o in group)
        verified.add(cid)
        safe_traces.append({'trace_id':trace_id,'correlation_id':cid,
                            'url': f"{run['base_url']}/project/{run['project']['id']}/traces/{trace_id}",
                            'observations':[{**{k:o.get(k) for k in fields},
                                'metadata':{k:o.get('metadata',{}).get(k) for k in metadata_fields if k in o.get('metadata',{})}}
                                for o in (root,retrieval,generation)]})
    by_cid = {t['correlation_id']:t for t in safe_traces}
    stages = []
    for stage in run['stages']:
        trace = by_cid.get(stage['correlation_id'])
        if trace:
            root = trace['observations'][0]
            assert str(root['metadata']['prompt_version']) == str(stage['version'])
            assert root['metadata']['prompt_label'] == stage['label']
            stages.append({**stage,'trace_id':trace['trace_id'],'url':trace['url']})
    log_rows = [json.loads(x) for x in (ROOT/'data/logs.jsonl').read_text(encoding='utf-8').splitlines()]
    log_ids = {r['correlation_id'] for r in log_rows if r.get('event') == 'response_sent' and r.get('correlation_id') in expected}
    evidence = {'project':run['project'], 'verified_at':datetime.now(timezone.utc).isoformat(),
                'expected_requests':len(expected), 'matching_log_responses':len(log_ids),
                'verified_traces':len(safe_traces), 'missing_ids':sorted(expected - verified),
                'stages':stages,'prompts':prompts,'traces':safe_traces}
    (EVIDENCE/'06-10-cloud-verification.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps({k:evidence[k] for k in ('expected_requests','matching_log_responses','verified_traces','missing_ids')}))
    assert verified == expected == log_ids, 'Cloud ingestion incomplete; retry after exporter flush'
    assert len(verified) >= 10
    print('PASS: parent tree, model, usage, cost, prompt link, correlation metadata, no raw IO; all stages verified.')


if __name__ == '__main__':
    main()
