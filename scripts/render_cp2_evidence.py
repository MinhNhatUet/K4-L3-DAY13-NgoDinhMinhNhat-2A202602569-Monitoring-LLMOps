"""Render verified Cloud API evidence (not Langfuse UI screenshots)."""
import json
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'submission/evidence'


def main():
    data = json.loads((OUT/'06-10-cloud-verification.json').read_text(encoding='utf-8'))
    project = data['project']['name']
    plt.style.use('seaborn-v0_8-whitegrid')

    def page(title, height=7):
        fig, ax = plt.subplots(figsize=(16, height), constrained_layout=True)
        fig.suptitle(f'{project}\n{title}', fontsize=16, fontweight='bold')
        fig.supxlabel(f"Verified Cloud API export | {data['verified_at']} | Not a Langfuse UI screenshot", fontsize=10)
        return fig, ax

    def save(fig, name):
        fig.savefig(OUT/name, dpi=120)
        plt.close(fig)

    fig, ax = page(f"Traces: {data['verified_traces']} verified / {data['matching_log_responses']} log responses", 9)
    ax.axis('off')
    rows = [[t['correlation_id'],t['trace_id'], 'root + retrieval + generation',t['observations'][2]['promptVersion']]
            for t in data['traces'][:15]]
    table = ax.table(cellText=rows, colLabels=['Correlation ID','Trace ID (first 15 shown)','Validated tree','Prompt version'],
                     colWidths=[.16,.38,.34,.12],loc='center',cellLoc='left')
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 2.1)
    save(fig,'06-trace-list.png')

    selected = next(t for t in data['traces'] if t['trace_id'] == data['stages'][-1]['trace_id'])
    fig, ax = page(f"Waterfall | trace {selected['trace_id']} | {selected['correlation_id']}", 6)
    obs = selected['observations']
    origin = datetime.fromisoformat(obs[0]['startTime'].replace('Z','+00:00'))
    for i,o in enumerate(obs):
        start = datetime.fromisoformat(o['startTime'].replace('Z','+00:00'))
        end = datetime.fromisoformat(o['endTime'].replace('Z','+00:00'))
        duration = (end-start).total_seconds()*1000
        offset = (start-origin).total_seconds()*1000
        ax.barh(i, max(duration,.1), left=offset,height=.45,color=['#334155','#0d9488','#2563eb'][i])
        ax.text(offset+duration+2,i,f'{duration:.1f} ms',va='center')
    ax.set_yticks(range(3),['lab-agent-run (AGENT)','  retrieval (RETRIEVER)','  generation (GENERATION)'])
    ax.invert_yaxis()
    ax.set_xlabel('Milliseconds since root start | Child parent IDs verified against root ID')
    ax.margins(x=.15)
    save(fig,'07-trace-waterfall.png')

    fig, ax = page('Root metadata and generation details | no raw input/output', 8)
    ax.axis('off')
    generation = obs[2]
    text = json.dumps({'trace_id':selected['trace_id'],'correlation_id':selected['correlation_id'],
                       'root_metadata':obs[0]['metadata'],
                       'generation':{k:generation[k] for k in ('model','promptName','promptVersion','usageDetails','costDetails','input','output')}},indent=2)
    ax.text(.03,.98,text,va='top',fontfamily='monospace',fontsize=11,transform=ax.transAxes)
    save(fig,'08-trace-metadata.png')

    fig, ax = page('Managed text prompts | final labels after rollback', 6)
    ax.axis('off')
    for i,p in enumerate(data['prompts']):
        ax.text(.04,.95-i*.47,f"{p['name']} v{p['version']} | type={p['type']} | labels={', '.join(p['labels'])}\n\n{p['prompt']}",
                va='top',fontfamily='monospace',fontsize=13,transform=ax.transAxes)
    save(fig,'09-prompt-versions.png')

    fig, ax = page('Promote and rollback verified with fresh API processes', 8)
    ax.axis('off')
    for i,stage in enumerate(data['stages']):
        ax.text(.03,.96-i*.24,
                f"{i+1}. {stage['stage'].upper()} | {stage['label']} -> v{stage['version']} | tokens_in={stage['tokens_in']}\n"
                f"    labels on version at this step: {', '.join(stage['labels'])}\n"
                f"    trace: {stage['trace_id']} | correlation: {stage['correlation_id']}\n"
                f"    UTC: {stage['at']}",va='top',fontfamily='monospace',fontsize=11,transform=ax.transAxes)
    save(fig,'10-prompt-rollback.png')
    print('Rendered evidence 06-10 from verified Cloud data.')


if __name__ == '__main__':
    main()
