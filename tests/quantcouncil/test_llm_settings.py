import pytest

from quantcouncil import llm_settings as llm
from tradingagents.llm_clients import create_tier_client

pytestmark = pytest.mark.unit


def test_keys_are_encrypted_and_masked():
    token = llm.encrypt("sk-test-1234567890abcd")
    assert "sk-test" not in token
    assert llm.decrypt(token) == "sk-test-1234567890abcd"
    assert llm.decrypt("not-a-token") is None
    assert llm.mask("sk-test-1234567890abcd") == "sk-tes...abcd"


def test_saved_key_wins_over_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert llm.api_key("openai", {}) == ("sk-env", "env")
    assert llm.api_key("openai", {"openai": llm.encrypt("sk-ui")}) == ("sk-ui", "ui")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.api_key("anthropic", {}) == (None, None)


def test_settings_map_to_core_overrides():
    s = llm.LLMSettings(provider="anthropic", quick_model="claude-sonnet-5", deep_model="claude-opus-5-5",
                        temperature=0.2, max_debate_rounds=2, output_language="English")
    o = llm.overrides(s, "sk-ant")
    assert o["llm_provider"] == "anthropic" and o["deep_think_llm"] == "claude-opus-5-5"
    assert o["max_debate_rounds"] == 2 and o["output_language"] == "English" and o["api_key"] == "sk-ant"
    assert llm.overrides(llm.LLMSettings(), None)["output_language"] is None  # "auto" keeps the market default


@pytest.mark.parametrize("provider,model", [("deepseek", "deepseek-flash"), ("openai", "gpt-6-luna"),
                                            ("anthropic", "claude-sonnet-5")])
def test_an_explicit_key_reaches_the_client_without_env(monkeypatch, provider, model):
    for env in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    cfg = {"llm_provider": provider, "quick_think_llm": model, "deep_think_llm": model, "api_key": "sk-from-ui"}
    client = create_tier_client(cfg, "quick").get_llm()
    secret = getattr(client, "openai_api_key", None) or getattr(client, "anthropic_api_key", None)
    assert secret.get_secret_value() == "sk-from-ui"


def test_catalog_lists_all_three_providers():
    cat = llm.catalog()
    assert set(cat) == {"deepseek", "openai", "anthropic"}
    assert all(cat[p]["quick"] and cat[p]["deep"] for p in cat)
