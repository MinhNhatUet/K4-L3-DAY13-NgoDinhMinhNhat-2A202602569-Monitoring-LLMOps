from app import mock_llm


def test_generation_links_template_and_reports_usage_cost_without_raw_io(monkeypatch):
    updates = []

    class Client:
        def update_current_generation(self, **kwargs):
            updates.append(kwargs)

    monkeypatch.setattr(mock_llm, 'get_langfuse_client', lambda: Client())
    monkeypatch.setattr(mock_llm.random, 'randint', lambda *_: 100)
    monkeypatch.setattr(mock_llm.time, 'sleep', lambda _: None)
    managed = object()
    response = mock_llm.FakeLLM.generate.__wrapped__(mock_llm.FakeLLM(), 'private question', managed_prompt=managed)
    assert updates[0]['prompt'] is managed
    assert updates[0]['model'] == response.model
    assert updates[1]['usage_details'] == {'input': 20, 'output': 100}
    assert updates[1]['cost_details']['total'] == .00156
    assert all('input' not in update and 'output' not in update for update in updates)
