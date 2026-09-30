from datetime import datetime, timezone
import math

from scripts.dashboard import summarize, window


def test_retrieval_denominator_includes_success_and_failure():
    rows = [
        {'event': 'request_received'}, {'event': 'request_received'},
        {'event': 'response_sent', 'tool_success': True, 'latency_ms': 150,
         'ttft_ms': 50, 'quality_score': .9, 'tokens_in': 20, 'tokens_out': 80, 'cost_usd': .01},
        {'event': 'request_failed', 'tool_success': False, 'error_type': 'RuntimeError'},
    ]
    summary = summarize(rows)
    assert summary['tool_success_rate_pct'] == 50
    assert summary['error_rate_pct'] == 50
    assert summary['tokens_in'] == 20
    assert summary['cost'] == .01
    assert summary['errors'] == {'RuntimeError': 1}
    assert math.isnan(summarize([])['tool_success_rate_pct'])


def test_window_uses_utc_and_excludes_old_and_future_data():
    now = datetime(2026, 9, 30, 3, 0, tzinfo=timezone.utc)
    rows = [{'ts': ts} for ts in ['2026-09-30T02:00:00Z', '2026-09-30T09:30:00+07:00',
                                 '2026-09-30T01:59:59Z', '2026-09-30T03:00:01Z']]
    assert [row for _, row in window(rows, now)] == rows[:2]
