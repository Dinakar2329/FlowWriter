import json
import threading
import httpx
import pytest
from flowwriter.domain import Provider, normalized_base_url, permits_key_transport
from flowwriter.provider import ChatClient, ProviderError, RequestCancelled

P = Provider("t", "Test", "http://localhost:11434/v1", "any-model", False)


def test_model_agnostic_completion():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "any-model"
        assert payload["stream"] is False
        assert "selected" in payload["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "Updated selected"}}]})
    chunks = []
    result = ChatClient(httpx.MockTransport(handler)).generate(P, "", "Refine", "selected", chunks.append)
    assert result == "Updated selected"
    assert chunks == ["Updated selected"]


def test_sse_streaming():
    body = ('data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
            'data: [DONE]\n\n')
    def handler(_):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
    chunks = []
    p = Provider(P.id, P.name, P.base_url, P.model, True)
    result = ChatClient(httpx.MockTransport(handler)).generate(p, "", "Summarize", "abc", chunks.append)
    assert result == "Hello world"
    assert chunks == ["Hello ", "Hello world"]


def test_invalid_json_and_auth_error():
    client = ChatClient(httpx.MockTransport(lambda _: httpx.Response(401, json={"error": "DO NOT LEAK"})))
    with pytest.raises(ProviderError) as caught:
        client.generate(P, "secret-key", "Refine", "selected")
    assert caught.value.code == "auth"
    assert "DO NOT LEAK" not in str(caught.value)
    client = ChatClient(httpx.MockTransport(lambda _: httpx.Response(200, text="not-json")))
    with pytest.raises(ProviderError) as caught:
        client.generate(P, "", "Refine", "selected")
    assert caught.value.code == "invalid_json"


def test_insecure_key_rejected_and_local_allowed():
    insecure = Provider("1", "Insecure", "http://192.168.1.40:4001/v1", "qwen2.5vl:latest")
    with pytest.raises(ProviderError) as caught:
        ChatClient().generate(insecure, "secret", "Summarize", "test")
    assert caught.value.code == "insecure_connection"
    assert not permits_key_transport(insecure.base_url)
    assert permits_key_transport(P.base_url)
    assert permits_key_transport("https://remote.example/v1")


def test_cancellation_before_connect():
    event = threading.Event()
    event.set()
    with pytest.raises(RequestCancelled):
        ChatClient().generate(P, "", "Refine", "text", cancel=event)


def test_base_url_contract():
    assert normalized_base_url("https://api.example/v1/") == "https://api.example/v1"
    for value in ("api.example/v1", "https://u:pass@api.example/v1", "https://api.example/v1/chat/completions"):
        with pytest.raises(ValueError):
            normalized_base_url(value)
