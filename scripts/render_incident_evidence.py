"""Export real incident evidence; label practice explicitly, never fake UI screenshots."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence',type=Path)
    args=parser.parse_args()
    data=json.loads(args.evidence.read_text(encoding='utf-8'))
    if 'verified_at' not in data:
        raise ValueError('Cloud verification must complete before rendering evidence')
    mode=data['mode'].upper()
    prefix='practice-' if data['mode']=='practice' else ''
    folder=ROOT/'submission/evidence'
    incident=data['phases'][1]
    cid=incident['selected_log']['correlation_id']
    title=f"{mode} | {data['project']['name']}"
    footer=f"Actual logs + verified Cloud API export (not UI screenshot) | {data['verified_at']}"
    plt.style.use('seaborn-v0_8-whitegrid')

    fig,axes=plt.subplots(1,2,figsize=(15,7),constrained_layout=True)
    fig.suptitle(f"{title}\nIncident metrics: baseline -> incident -> recovered\nUTC {incident['started_at']} to {incident['ended_at']}",fontsize=14)
    names=[p['name'] for p in data['phases']]
    for ax,key,label in zip(axes,('error_rate_pct','tool_success_rate_pct'),('Request error rate (%)','Retrieval success (%)')):
        values=[p['metrics'][key] for p in data['phases']]
        ax.bar(names,values,color=['#2563eb','#dc2626','#0d9488'])
        for i,value in enumerate(values):
            ax.text(i,value+2,f'{value:.1f}% (n={data["phases"][i]["metrics"]["requests"]})',ha='center')
        ax.axhline(2 if key=='error_rate_pct' else 90,linestyle='--',color='#d97706',label='Guardrail')
        ax.set_ylim(0,115)
        ax.set_title(label)
        ax.legend()
    fig.supxlabel(f"Representative incident request: {cid}\n{footer}",fontsize=10)
    fig.savefig(folder/f'12-{prefix}incident-metric.png',dpi=120)
    plt.close(fig)

    fig,ax=plt.subplots(figsize=(15,9),constrained_layout=True)
    ax.axis('off')
    fig.suptitle(f"{title}\nActual data/logs.jsonl line {incident['selected_log_line']} | {cid}",fontsize=14)
    ax.text(.02,.97,json.dumps(incident['selected_log'],indent=2),va='top',fontfamily='monospace',fontsize=12,transform=ax.transAxes)
    fig.supxlabel(footer,fontsize=10)
    fig.savefig(folder/f'13-{prefix}incident-log.png',dpi=120)
    plt.close(fig)

    fig,ax=plt.subplots(figsize=(16,7),constrained_layout=True)
    ax.axis('off')
    fig.suptitle(f"{title}\nTrace: {incident['trace_id']} | {cid}",fontsize=14)
    observations=sorted(incident['observations'],key=lambda o:(o['parentObservationId'] is not None,o['startTime']))
    lines=[]
    for o in observations:
        lines += [f"{o['name']} [{o['type']}] level={o['level']}",
                  f"  id={o['id']} parent={o['parentObservationId']}",
                  f"  status={o['statusMessage'] or '(none)'}",
                  f"  UTC: {o['startTime']} -> {o['endTime']}", '']
    lines += [f"Observed retrieval duration: {incident['retrieval_duration_ms']:.1f} ms",
              f"Generation observation present: {any(o['name']=='generation' for o in observations)}",
              'Raw input/output: null on all exported observations']
    ax.text(.02,.95,'\n'.join(lines),va='top',fontfamily='monospace',fontsize=12,transform=ax.transAxes)
    fig.supxlabel(footer,fontsize=10)
    fig.savefig(folder/f'14-{prefix}incident-trace.png',dpi=120)
    plt.close(fig)
    print('Rendered incident metric, log, and trace evidence.')


if __name__=='__main__':
    main()
