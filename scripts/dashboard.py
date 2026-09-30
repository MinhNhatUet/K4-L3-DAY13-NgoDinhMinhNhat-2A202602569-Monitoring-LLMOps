"""Six-panel dashboard from JSONL; run with the separate dashboard venv."""
from __future__ import annotations

import argparse
import io
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, p):
    if not values:
        return math.nan
    values = sorted(values)
    position = (len(values) - 1) * p / 100
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def summarize(rows):
    received = [r for r in rows if r.get('event') == 'request_received']
    success = [r for r in rows if r.get('event') == 'response_sent']
    failures = [r for r in rows if r.get('event') == 'request_failed']
    tools = [r for r in rows if isinstance(r.get('tool_success'), bool)]
    return {
        'requests': len(received),
        'p50': percentile([r['latency_ms'] for r in success], 50),
        'p95': percentile([r['latency_ms'] for r in success], 95),
        'p99': percentile([r['latency_ms'] for r in success], 99),
        'ttft_p95': percentile([r['ttft_ms'] for r in success], 95),
        'error_rate_pct': 100 * len(failures) / len(received) if received else math.nan,
        'tool_success_rate_pct': 100 * sum(r['tool_success'] for r in tools) / len(tools) if tools else math.nan,
        'cost': sum(r.get('cost_usd', 0) for r in success),
        'tokens_in': sum(r.get('tokens_in', 0) for r in success),
        'tokens_out': sum(r.get('tokens_out', 0) for r in success),
        'quality': mean(r['quality_score'] for r in success) if success else math.nan,
        'errors': dict(Counter(r.get('error_type', 'unknown') for r in failures)),
    }


def window(rows, now, minutes=60):
    start = now - timedelta(minutes=minutes)
    result = []
    for row in rows:
        ts = datetime.fromisoformat(row['ts'].replace('Z', '+00:00'))
        if ts.tzinfo is None:
            raise ValueError('Log timestamps must include a timezone')
        if start <= ts <= now:
            result.append((ts, row))
    return result


def render(log_path, config_path, now=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import yaml

    now = now or datetime.now(timezone.utc)
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))['dashboard']
    rows, skipped = [], 0
    for line in log_path.read_text(encoding='utf-8').splitlines() if log_path.exists() else []:
        try:
            row = json.loads(line)
            if not row.get('ts'):
                raise ValueError('missing timestamp')
            window([row], now, config['time_range_minutes'])
            rows.append(row)
        except (ValueError, TypeError):
            skipped += 1
    selected = window(rows, now, config['time_range_minutes'])
    summary = summarize([r for _, r in selected])
    start = now - timedelta(minutes=config['time_range_minutes'])
    first = start.replace(second=0, microsecond=0)
    times = [first + timedelta(minutes=i) for i in range(config['time_range_minutes'] + 1)]
    buckets = [summarize([r for ts, r in selected if t <= ts < t + timedelta(minutes=1)]) for t in times]
    plt.style.use('seaborn-v0_8-whitegrid')
    fig, axes = plt.subplots(3, 2, figsize=(18, 13), constrained_layout=True)
    fig.suptitle(f"{config['title']}\nLast 60 minutes | UTC {start:%H:%M:%S} - {now:%H:%M:%S} | Refresh 30s | Requests {summary['requests']}", fontsize=17)

    def line(ax, key, label, cumulative=False):
        values = [b[key] for b in buckets]
        if cumulative:
            total = 0
            values = [(total := total + v) for v in values]
        ax.plot(times, values, label=label, marker='.', linewidth=1.7)

    for ax, panel in zip(axes.flat, config['panels']):
        key = panel['id']
        ax.set_title(panel['title'], loc='left', fontweight='bold')
        ax.set_ylabel(panel['unit'])
        if key == 'latency':
            for metric in ('p50', 'p95', 'p99', 'ttft_p95'):
                line(ax, metric, f"{metric}: {summary[metric]:.1f} ms")
        elif key == 'traffic':
            line(ax, 'requests', 'Requests / minute')
        elif key == 'errors':
            line(ax, 'error_rate_pct', f"Errors: {summary['error_rate_pct']:.1f}%")
            line(ax, 'tool_success_rate_pct', f"Retrieval success: {summary['tool_success_rate_pct']:.1f}%")
            ax.axhline(90, color='#d97706', linestyle=':', label='Retrieval floor: 90%')
            ax.set_ylim(-5, 105)
            ax.text(.01, .03, f"Error types: {summary['errors'] or 'none'}", transform=ax.transAxes, fontsize=8)
        elif key == 'cost':
            line(ax, 'cost', 'USD / minute')
            line(ax, 'cost', f"Window cumulative: ${summary['cost']:.4f}", cumulative=True)
        elif key == 'tokens':
            for metric in ('tokens_in', 'tokens_out'):
                line(ax, metric, f"{metric} cumulative: {summary[metric]}", cumulative=True)
        elif key == 'quality':
            line(ax, 'quality', f"Mean quality: {summary['quality']:.3f}")
            ax.set_ylim(0, 1.05)
        threshold = panel['threshold']
        ax.axhline(threshold['value'], color='#dc2626', linestyle='--', linewidth=1, label=f"{threshold['aggregation']} {threshold['operator']} {threshold['value']}")
        ax.set_xlim(start, now)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=timezone.utc))
        ax.set_xlabel('UTC | 1-minute buckets (empty latency/quality/rate = gaps)')
        ax.legend(fontsize=8, loc='best')
    fig.supxlabel(f"Source: data/logs.jsonl | Invalid/incomplete lines skipped: {skipped} | Cost threshold is for displayed 60m; daily SLO guardrail is separate", fontsize=10)
    output = io.BytesIO()
    fig.savefig(output, format='png', dpi=120)
    plt.close(fig)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'submission/evidence/11-dashboard-overview.png')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args()
    log_path, config_path = ROOT/'data/logs.jsonl', ROOT/'config/dashboard.yaml'
    if not args.serve:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(render(log_path, config_path))
        print(args.output)
        return

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split('?')[0] == '/dashboard.png':
                content, mime = render(log_path, config_path), 'image/png'
            elif self.path == '/':
                content = b'<!doctype html><html><head><title>LLMOps dashboard</title><meta http-equiv="refresh" content="30"></head><body style="margin:0"><img style="width:100%" src="/dashboard.png" alt="Six monitoring panels, last 60 minutes UTC"></body></html>'
                mime = 'text/html; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(content)

    print(f'Dashboard: http://127.0.0.1:{args.port} (refresh 30s)', flush=True)
    HTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
