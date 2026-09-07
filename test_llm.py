"""
Tests for the model provider layer.

No API key and no network: the provider SDKs are replaced with stubs that
record what they were handed. What is being checked is the wiring — role
translation, config plumbing, and error messages — not the models themselves.

    python test_llm.py
"""

import importlib
import os
import sys
import types

failures = []


def check(label, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (label, got, want))


def check_raises(label, fn, expect_substring):
    try:
        fn()
    except Exception as e:
        if expect_substring.lower() not in str(e).lower():
            failures.append("%s: message %r lacks %r" % (label, str(e), expect_substring))
        return
    failures.append("%s: expected an exception, none raised" % label)


def load_llm(**env):
    """Reimport llm.py with a specific environment. PROVIDER is read at import."""
    for key in ("LLM_PROVIDER", "ASTRO_MODEL", "LLM_MAX_TOKENS",
                "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(key, None)
    os.environ.update(env)
    sys.modules.pop("llm", None)
    return importlib.import_module("llm")


HISTORY = [
    {"role": "user", "content": "first question"},
    {"role": "assistant", "content": "first answer"},
    {"role": "user", "content": "second question"},
]

# ---------------------------------------------------------------
# 1. Defaults and model selection.
# ---------------------------------------------------------------
llm = load_llm()
check("default provider", llm.PROVIDER, "anthropic")
check("default anthropic model", llm.current_model(), "claude-opus-5")
check("default max tokens", llm.MAX_OUTPUT_TOKENS, 4000)

llm = load_llm(LLM_PROVIDER="gemini")
check("gemini default model", llm.current_model(), "gemini-3.8-flash")

llm = load_llm(LLM_PROVIDER="gemini", ASTRO_MODEL="gemini-2.5-flash")
check("ASTRO_MODEL overrides", llm.current_model(), "gemini-2.5-flash")

llm = load_llm(LLM_MAX_TOKENS="1234")
check("LLM_MAX_TOKENS honoured", llm.MAX_OUTPUT_TOKENS, 1234)

# Case-insensitive, so LLM_PROVIDER=Gemini does not silently fall through.
llm = load_llm(LLM_PROVIDER="GEMINI")
check("provider is lowercased", llm.PROVIDER, "gemini")

# ---------------------------------------------------------------
# 2. Missing keys produce actionable errors, not tracebacks.
# ---------------------------------------------------------------
llm = load_llm(LLM_PROVIDER="anthropic")
check_raises("anthropic without key",
             lambda: llm.generate("sys", HISTORY), "ANTHROPIC_API_KEY")

llm = load_llm(LLM_PROVIDER="gemini")
check_raises("gemini without key",
             lambda: llm.generate("sys", HISTORY), "GEMINI_API_KEY")

llm = load_llm(LLM_PROVIDER="nonsense")
check_raises("unknown provider",
             lambda: llm.generate("sys", HISTORY), "Unknown provider")

# ---------------------------------------------------------------
# 3. Gemini wiring: roles translated, system prompt and token cap passed
#    through, and the full history sent every call (statelessness).
# ---------------------------------------------------------------
captured = {}


class _FakeModels:
    def generate_content(self, *, model, contents, config):
        captured["model"] = model
        captured["contents"] = contents
        captured["config"] = config
        return types.SimpleNamespace(text="a reading", candidates=[])


class _FakeClient:
    def __init__(self, api_key=None):
        captured["api_key"] = api_key
        self.models = _FakeModels()


llm = load_llm(LLM_PROVIDER="gemini", GEMINI_API_KEY="test-key")
import google.genai as real_genai  # noqa: E402

original_client = real_genai.Client
real_genai.Client = _FakeClient
try:
    answer = llm.generate("THE SYSTEM PROMPT", HISTORY, max_tokens=999)
finally:
    real_genai.Client = original_client

check("gemini returns text", answer, "a reading")
check("gemini gets the api key", captured["api_key"], "test-key")

# The client must be held, not created as a temporary — an unreferenced client
# can be collected mid-request, closing its transport ("Cannot send a request,
# as the client has been closed").
check("client is cached, not rebuilt per call", len(llm._clients), 1)
check("gemini gets the model", captured["model"], "gemini-3.8-flash")
check("system prompt passed through",
      captured["config"].system_instruction, "THE SYSTEM PROMPT")
check("max_tokens passed through", captured["config"].max_output_tokens, 999)

# Statelessness: every turn of history is sent, none dropped.
check("all turns sent", len(captured["contents"]), 3)

# Role translation: Anthropic's "assistant" must become Gemini's "model".
check("roles translated",
      [c.role for c in captured["contents"]], ["user", "model", "user"])
check("no assistant role leaks",
      any(c.role == "assistant" for c in captured["contents"]), False)
check("text preserved",
      [c.parts[0].text for c in captured["contents"]],
      ["first question", "first answer", "second question"])

# ---------------------------------------------------------------
# 4. An empty Gemini response is reported, not returned as a blank reading.
# ---------------------------------------------------------------
class _BlockedModels:
    def generate_content(self, *, model, contents, config):
        return types.SimpleNamespace(
            text=None,
            candidates=[types.SimpleNamespace(finish_reason="SAFETY")])


class _BlockedClient:
    def __init__(self, api_key=None):
        self.models = _BlockedModels()


real_genai.Client = _BlockedClient
llm._clients.clear()          # clients are cached per key; drop the fake above
try:
    check_raises("blocked response surfaces reason",
                 lambda: llm.generate("sys", HISTORY), "SAFETY")
finally:
    real_genai.Client = original_client
    llm._clients.clear()

# ---------------------------------------------------------------
# 5. Anthropic wiring: roles left alone, system passed as its own argument.
# ---------------------------------------------------------------
anthropic_captured = {}


class _FakeMessages:
    def create(self, *, model, max_tokens, system, messages):
        anthropic_captured.update(
            model=model, max_tokens=max_tokens, system=system, messages=messages)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="claude reading")])


class _FakeAnthropic:
    def __init__(self, api_key=None):
        self.messages = _FakeMessages()


llm = load_llm(LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="test-key")

# Stub the anthropic package if it is not installed, so this test runs with
# neither provider SDK present. llm.py imports it inside the function, so a
# sys.modules entry is enough.
try:
    import anthropic as real_anthropic  # noqa: E402
    original_anthropic = real_anthropic.Anthropic
    restore = lambda: setattr(real_anthropic, "Anthropic", original_anthropic)
    real_anthropic.Anthropic = _FakeAnthropic
except ImportError:
    stub = types.ModuleType("anthropic")
    stub.Anthropic = _FakeAnthropic
    sys.modules["anthropic"] = stub
    restore = lambda: sys.modules.pop("anthropic", None)

try:
    answer = llm.generate("THE SYSTEM PROMPT", HISTORY)
finally:
    restore()

check("anthropic returns text", answer, "claude reading")
check("anthropic default model", anthropic_captured["model"], "claude-opus-5")
check("anthropic system separate", anthropic_captured["system"], "THE SYSTEM PROMPT")
check("anthropic roles untouched",
      [m["role"] for m in anthropic_captured["messages"]],
      ["user", "assistant", "user"])
check("anthropic max tokens default", anthropic_captured["max_tokens"], 4000)

# ---------------------------------------------------------------
# 6. Model selection. The model name arrives from the browser, so anything
#    not on the allow-list must be refused rather than passed through — an
#    unchecked string would let a caller bill this account against any model
#    the key can reach.
# ---------------------------------------------------------------
llm = load_llm(LLM_PROVIDER="gemini", GEMINI_API_KEY="test-key")

check_raises("unknown model refused",
             lambda: llm.generate("sys", HISTORY, model="gpt-4"),
             "Unknown model")
check_raises("model injection refused",
             lambda: llm.generate("sys", HISTORY, model="../../etc/passwd"),
             "Unknown model")

# A model whose provider has no key must say so, not fail obscurely later.
check_raises("model without its key",
             lambda: llm.generate("sys", HISTORY, model="claude-opus-5"),
             "ANTHROPIC_API_KEY")

# Only choices this deployment can serve are offered.
ids = [c["id"] for c in llm.available_choices()]
check("only gemini offered without an anthropic key",
      all(i.startswith("gemini") for i in ids), True)
check("gemini choices present", "gemini-3.8-flash" in ids, True)

llm = load_llm(LLM_PROVIDER="gemini", GEMINI_API_KEY="k1",
               ANTHROPIC_API_KEY="k2")
ids = [c["id"] for c in llm.available_choices()]
for expected in ("gemini-3.8-flash", "claude-sonnet-5", "claude-opus-5"):
    check("%s offered when both keys set" % expected, expected in ids, True)
check("default is listed first",
      llm.available_choices()[0]["is_default"], True)
check("default matches current_model",
      llm.available_choices()[0]["id"], llm.current_model())

# Choosing an Anthropic model must route to the Anthropic backend even though
# LLM_PROVIDER says gemini — that is the whole point of the selector.
routed = {}


class _RoutedMessages:
    def create(self, *, model, max_tokens, system, messages):
        routed["model"] = model
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="from claude")])


class _RoutedAnthropic:
    def __init__(self, api_key=None):
        self.messages = _RoutedMessages()


stub = types.ModuleType("anthropic")
stub.Anthropic = _RoutedAnthropic
sys.modules["anthropic"] = stub
llm._clients.clear()
try:
    answer = llm.generate("sys", HISTORY, model="claude-sonnet-5")
    check("routed to anthropic", answer, "from claude")
    check("routed with the chosen model", routed.get("model"), "claude-sonnet-5")
finally:
    sys.modules.pop("anthropic", None)
    llm._clients.clear()

# ---------------------------------------------------------------
# 7. Provider failures are translated into something actionable. A 503 is the
#    provider's problem, and the raw exception buries that in a stack trace.
# ---------------------------------------------------------------
translate = llm._readable_provider_failure
check("503 mentions overload",
      "overloaded" in str(translate(Exception("503 UNAVAILABLE"), "m")).lower(),
      True)
check("503 suggests another model",
      "different model" in str(translate(Exception("503 UNAVAILABLE"), "m")),
      True)
check("429 mentions rate limit",
      "rate limit" in str(translate(Exception("429 Too Many Requests"), "m")).lower(),
      True)
check("billing mentions credit",
      "credit" in str(translate(Exception("insufficient credit balance"), "m")).lower(),
      True)
check("401 mentions the key",
      "key" in str(translate(Exception("401 unauthorized"), "m")).lower(),
      True)
# An unrecognised failure must keep its original text — guessing would hide
# the only clue to a real bug.
check("unknown failure keeps its text",
      "something odd happened" in str(
          translate(Exception("something odd happened"), "m")),
      True)

if failures:
    print("FAILED (%d)" % len(failures))
    for f in failures:
        print("  -", f)
    sys.exit(1)

print("All provider layer tests passed.")
