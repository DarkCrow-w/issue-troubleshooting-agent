"""模型客户端生命周期回归测试。"""

from types import SimpleNamespace

from troubleshooter.models import client as client_module
from troubleshooter.models.client import ModelClient


class ClosableClient:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class ClosableSyncClient(ClosableClient):
    def close(self):
        self.closed = True


class SharedModel:
    """模拟 LangChain 多个模型对象共用底层 HTTP 客户端。"""

    def __init__(self):
        self.root_async_client = ClosableClient()
        self.root_client = ClosableSyncClient()


def test_task_cleanup_does_not_close_langchain_shared_http_client(monkeypatch):
    model = SharedModel()
    settings = SimpleNamespace(
        llm_model="test-model",
        llm_base_url="https://example.invalid/v1",
        llm_api_key="test-key",
        llm_max_output_tokens=32,
        llm_timeout_seconds=10,
        llm_enable_thinking=False,
    )
    monkeypatch.setattr(client_module, "init_chat_model", lambda *args, **kwargs: model)
    client = ModelClient(settings, SimpleNamespace())
    client._get_model()

    # 每笔任务结束时，ModelClient 不应提供关闭共享连接的方法。
    close = getattr(client, "aclose", None)
    assert close is None

    assert model.root_async_client.closed is False
    assert model.root_client.closed is False
