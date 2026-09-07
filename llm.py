"""
Model provider layer — one interface, two backends.

    LLM_PROVIDER=anthropic   (default)  -> Claude, via the anthropic SDK
    LLM_PROVIDER=gemini                 -> Gemini, via google-genai

`generate()` below is the whole contract. astro_personas.ask_astrologer()
calls it and does not know which provider answered, so switching is an
environment variable rather than a code change — and you can put the same
chart to both and compare the readings.

Both paths are deliberately STATELESS: the full conversation is sent on every
call. Gemini's Interactions API offers server-side conversation state via
previous_interaction_id, and it is the wrong tool here. This app re-attaches a
freshly computed chart block to each question and stores history without it
(see "The one invariant" in CLAUDE.md); server-side state would retain the
first turn's chart and answer from a stale sky.
"""

import os

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()

# An eight-section reading with a six-to-ten sentence summary does not fit in
# 2000 tokens, which is what ask_astrologer() used before the provider split
# (the Flask endpoint already used 4000 — the two had drifted apart). One
# setting for both paths now.
MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4000"))

DEFAULT_MODELS = {
    "anthropic": "claude-opus-5",
    # Free tier at time of writing. gemini-2.5-flash is a lighter alternative.
    "gemini": "gemini-3.8-flash",
}


def current_model():
    """The model that generate() will use, for display and logging."""
    return os.environ.get("ASTRO_MODEL") or DEFAULT_MODELS[PROVIDER]


class ProviderError(RuntimeError):
    """Raised with an actionable message when a provider cannot answer."""


# ---------------------------------------------------------------- anthropic

def _generate_anthropic(system, messages, max_tokens):
    # Check configuration before importing. If the SDK is also missing, an
    # ImportError would otherwise mask the message that actually helps.
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ProviderError(
            "ANTHROPIC_API_KEY is not set. Get one at console.anthropic.com, "
            "or set LLM_PROVIDER=gemini to use Gemini's free tier instead."
        )

    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise ProviderError(
            "LLM_PROVIDER=anthropic but the anthropic package is not installed. "
            "Run: pip install anthropic"
        ) from e

    response = Anthropic(api_key=key).messages.create(
        model=current_model(),
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return "".join(b.text for b in response.content if b.type == "text")


# ------------------------------------------------------------------ gemini

def _generate_gemini(system, messages, max_tokens):
    # Configuration before import, for the same reason as the Anthropic path.
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise ProviderError(
            "GEMINI_API_KEY is not set. Get a free key at aistudio.google.com/apikey."
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise ProviderError(
            "LLM_PROVIDER=gemini but the google-genai package is not installed. "
            "Run: pip install google-genai"
        ) from e

    # Gemini names the assistant role "model"; Anthropic calls it "assistant".
    # The rest of the app speaks Anthropic's vocabulary, so translate here.
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]

    response = genai.Client(api_key=key).models.generate_content(
        model=current_model(),
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
        ),
    )

    text = response.text
    if not text:
        # An empty response is usually a safety block, not a bug. Readings touch
        # health, death and marriage, so this is a live possibility — surface the
        # reason instead of returning a blank answer to the querent.
        reason = None
        try:
            reason = response.candidates[0].finish_reason
        except (AttributeError, IndexError, TypeError):
            pass
        raise ProviderError(
            "Gemini returned no text"
            + (f" (finish_reason: {reason})." if reason else ".")
            + " If this was a safety filter, the question may need rephrasing, "
              "or set LLM_PROVIDER=anthropic for this reading."
        )
    return text


# ------------------------------------------------------------------ public

_BACKENDS = {"anthropic": _generate_anthropic, "gemini": _generate_gemini}


def generate(system, messages, max_tokens=None):
    """
    Ask the configured provider for one completion.

    system:   the full system prompt (personas + shared rules)
    messages: [{"role": "user"|"assistant", "content": str}, ...] — the entire
              conversation, sent in full every call
    """
    backend = _BACKENDS.get(PROVIDER)
    if backend is None:
        raise ProviderError(
            f"Unknown LLM_PROVIDER {PROVIDER!r}. "
            f"Expected one of: {', '.join(sorted(_BACKENDS))}."
        )
    return backend(system, messages, max_tokens or MAX_OUTPUT_TOKENS)
