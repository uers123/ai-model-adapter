from .mock import MockAdapter
from .next_gpt import NextGPTAdapter


def adapter_for(model_id: str):
    if model_id.lower() in {"mock", "mock-model", "simulator"}:
        return MockAdapter()
    if model_id.lower() in {"next-gpt", "nextgpt", "nex t-gpt"}:
        return NextGPTAdapter()
    return NextGPTAdapter() if "next" in model_id.lower() else MockAdapter()
