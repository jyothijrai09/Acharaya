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

# Gemini's free tier is the default: a deployment with no billing set up
# should still work, and should not be able to spend money by accident.
PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()

# An eight-section reading with a six-to-ten sentence summary does not fit in
# 2000 tokens, which is what ask_astrologer() used before the provider split
# (the Flask endpoint already used 4000 — the two had drifted apart). One
# setting for both paths now.
# 4000 was far too low, and the way it failed was expensive and silent.
# Claude Sonnet 5 and Opus 5 run adaptive thinking by DEFAULT, and thinking
# is billed and counted against max_tokens. A life reading at 4000 spent
# the entire budget thinking and returned zero text blocks: a 54-second
# call, seven cents, and an empty reading saved to the cache.
#
# The budget now has room for the thinking AND the answer.
MAX_OUTPUT_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "12000"))

# How hard the model thinks before answering. Thinking improves a reading
# of this kind, but it costs time, and Vercel's Hobby plan kills a function
# at 60 seconds - a life reading at default effort already took 54. 'medium'
# keeps the quality while leaving headroom. Raise it if you move off Hobby.
LLM_EFFORT = os.environ.get("LLM_EFFORT", "medium")

# Milliseconds a single provider call may take. This exists because of the
# platform, not the model: Vercel's Hobby plan kills a function at 60
# seconds, and google-genai retries a 503 internally with backoff. A busy
# Gemini therefore burned the entire budget retrying and the request died
# as a 504 - a bare error page, not JSON, which the browser could not even
# parse into a message. Failing at 40s leaves room to return a real one.
PROVIDER_TIMEOUT_MS = int(os.environ.get("PROVIDER_TIMEOUT_MS", "40000"))

# Attempts INCLUDING the first. Two is deliberate: one retry catches a
# blip, more just spends the function's remaining life on a provider that
# has already said it is overloaded.
PROVIDER_ATTEMPTS = int(os.environ.get("PROVIDER_ATTEMPTS", "2"))

DEFAULT_MODELS = {
    "anthropic": "claude-opus-5",
    "gemini": "gemini-3.8-flash",
}

# What a person may choose from. An allow-list rather than free text:
# the model name reaches this from the browser, and an unchecked string
# would let anyone bill the account against any model the key can reach.
CHOICES = [
    {"id": "gemini-3.8-flash", "provider": "gemini",
     "label": "Gemini 3.8 Flash", "cost": "free tier"},
    {"id": "gemini-2.5-flash", "provider": "gemini",
     "label": "Gemini 2.5 Flash", "cost": "free tier, older"},
    {"id": "claude-sonnet-5", "provider": "anthropic",
     "label": "Claude Sonnet 5", "cost": "$2 / $10 per Mtok"},
    {"id": "claude-opus-5", "provider": "anthropic",
     "label": "Claude Opus 5", "cost": "$5 / $25 per Mtok"},
]

BY_ID = {c["id"]: c for c in CHOICES}

# US dollars per million tokens, (input, output). Gemini's free tier bills
# nothing, so a reading on it costs zero and never touches the budget.
#
# These are list prices and they change. They are used to enforce a spending
# cap, so being slightly out matters: if a price rises and this table does not,
# the cap under-counts and the real bill goes past it. Check it against the
# provider's pricing page if the numbers ever look wrong.
PRICES = {
    "gemini-3.8-flash": (0.0, 0.0),
    "gemini-2.5-flash": (0.0, 0.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
}

# Cached input is billed at a fraction of the normal rate: a write costs 1.25x
# and a read 0.1x. Ignoring this would overstate the cost of every cached call
# and make the budget bite far earlier than it should.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


def cost_of(model, usage):
    """
    What one call cost, in dollars, from the token counts the provider returned.

    usage keys: input, output, cache_write, cache_read - any of which may be
    absent. Returns 0.0 for a model with no price, which is the correct answer
    for a free tier rather than a reason to refuse the reading.
    """
    if not usage:
        return 0.0
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    if not price_in and not price_out:
        return 0.0

    def n(key):
        value = usage.get(key)
        return value if isinstance(value, (int, float)) else 0

    billable_input = (
        n("input")
        + n("cache_write") * CACHE_WRITE_MULTIPLIER
        + n("cache_read") * CACHE_READ_MULTIPLIER
    )
    return round(billable_input * price_in / 1_000_000
                 + n("output") * price_out / 1_000_000, 6)


def provider_available(provider):
    """Whether the key for a provider is present. Offering a model the
    server cannot reach would only produce a confusing failure."""
    if provider == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY")
                    or os.environ.get("GOOGLE_API_KEY"))
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return False


def available_choices():
    """The choices this deployment can actually serve, default first."""
    default = current_model()
    out = [dict(c, is_default=(c["id"] == default))
           for c in CHOICES if provider_available(c["provider"])]
    out.sort(key=lambda c: (not c["is_default"], c["provider"]))
    return out


def current_model():
    """The model that generate() will use, for display and logging."""
    return os.environ.get("ASTRO_MODEL") or DEFAULT_MODELS[PROVIDER]


class ProviderError(RuntimeError):
    """Raised with an actionable message when a provider cannot answer."""


def _readable_provider_failure(exc, model):
    """Turn an SDK exception into something worth showing a querent.

    The common failures here are the provider's, not the app's: the model
    is overloaded, or the account is rate limited or out of credit. Left
    raw, those surface as a paragraph of stack trace that reads like a
    bug in the reading, and the one useful instruction — try a different
    model — is nowhere in it."""
    text = str(exc)
    lowered = text.lower()

    if "503" in text or "unavailable" in lowered or "overloaded" in lowered:
        return ProviderError(
            f"{model} is overloaded right now — the provider is asking us "
            f"to try again shortly. This is on their side, not your chart. "
            f"Wait a moment and ask again, or pick a different model."
        )
    if "timeout" in lowered or "timed out" in lowered:
        return ProviderError(
            f"{model} took too long and the request was cut off. A life or "
            f"yearly reading is the longest of these; try a faster model, or "
            f"ask again when the provider is less busy."
        )
    if "429" in text or "rate limit" in lowered or "quota" in lowered:
        return ProviderError(
            f"{model} has hit its rate limit or quota. Free tiers cap how "
            f"often you can ask. Wait a little, or pick a different model."
        )
    if "credit" in lowered or "billing" in lowered or "payment" in lowered:
        return ProviderError(
            f"{model} refused the request for billing reasons — usually no "
            f"credit on the account. Add credit, or pick a different model."
        )
    if "401" in text or "403" in text or "api key" in lowered:
        return ProviderError(
            f"{model} rejected the API key. Check it is set correctly and "
            f"has not been revoked."
        )

    # Anything unrecognised keeps its original text: a wrong guess here
    # would hide the only clue to a genuine bug.
    return ProviderError(f"{model} could not answer: {text}")


# Clients are cached per key and kept alive for the life of the process.
#
# The cache is not only an optimisation. Written inline as
# genai.Client(...).models.generate_content(...) the client is a temporary
# with no reference held, so CPython may collect it as soon as the attribute
# lookup completes — closing the pooled HTTP transport out from under the
# in-flight request. That surfaces to the querent as the opaque
# "Cannot send a request, as the client has been closed".
#
# Both SDKs document their clients as reusable and thread-safe, so holding one
# is the intended usage, and it saves re-establishing TLS on every question.
# Unlike a database connection this is safe to keep across serverless
# invocations: a frozen or discarded instance takes its sockets with it.
_clients = {}

# Token counts from the most recent call, for the admin page. Not a running
# total: it is a snapshot, and a serverless instance may serve one request
# or a hundred, so it says what the last question cost rather than pretending
# to bill.
LAST_USAGE = {}


def _gemini_client(key):
    if ("gemini", key) not in _clients:
        from google import genai
        from google.genai import types as gtypes
        _clients[("gemini", key)] = genai.Client(
            api_key=key,
            http_options=gtypes.HttpOptions(
                timeout=PROVIDER_TIMEOUT_MS,
                retry_options=gtypes.HttpRetryOptions(
                    attempts=PROVIDER_ATTEMPTS,
                    max_delay=5.0,
                ),
            ),
        )
    return _clients[("gemini", key)]


def _anthropic_client(key):
    if ("anthropic", key) not in _clients:
        from anthropic import Anthropic
        # Seconds here, unlike google-genai's milliseconds.
        _clients[("anthropic", key)] = Anthropic(
            api_key=key,
            timeout=PROVIDER_TIMEOUT_MS / 1000.0,
            max_retries=max(0, PROVIDER_ATTEMPTS - 1),
        )
    return _clients[("anthropic", key)]


# ---------------------------------------------------------------- anthropic

def _generate_anthropic(system, messages, max_tokens, model=None):
    # Check configuration before importing. If the SDK is also missing, an
    # ImportError would otherwise mask the message that actually helps.
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ProviderError(
            "ANTHROPIC_API_KEY is not set. Get one at console.anthropic.com, "
            "or set LLM_PROVIDER=gemini to use Gemini's free tier instead."
        )

    try:
        client = _anthropic_client(key)
    except ImportError as e:
        raise ProviderError(
            "LLM_PROVIDER=anthropic but the anthropic package is not installed. "
            "Run: pip install anthropic"
        ) from e

    # The system prompt is the persona plus the twenty-two rules, and it is
    # byte-identical on every call for a given persona - about 5,000 tokens
    # re-sent with every question. Marking it cached costs 1.25x once and
    # 0.1x on every read after, so it pays for itself from the second
    # question onward and saves roughly 90% of the input on all the rest.
    #
    # The chart block deliberately stays OUT of the cache: it is rebuilt from
    # the ephemeris every call and changes as transits move, so it would
    # never produce a hit and would only pay the write premium. It is sent
    # after this breakpoint, which is exactly where volatile content belongs.
    request = {
        "model": model or current_model(),
        "max_tokens": max_tokens,
        "system": [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        "messages": messages,
    }
    if LLM_EFFORT:
        request["output_config"] = {"effort": LLM_EFFORT}

    try:
        response = client.messages.create(**request)
    except Exception as e:
        # An unsupported effort value should not cost the reading; retry
        # without it rather than failing the whole request.
        if "output_config" in request and "effort" in str(e).lower():
            request.pop("output_config")
            try:
                response = client.messages.create(**request)
            except Exception as e2:
                raise _readable_provider_failure(e2, model or current_model())
        else:
            raise _readable_provider_failure(e, model or current_model())

    # Worth watching: if cache_read_input_tokens stays at zero across
    # repeated questions, something is changing the prompt between calls and
    # the discount is being paid for without being collected.
    usage = getattr(response, 'usage', None)
    if usage is not None:
        LAST_USAGE.clear()
        LAST_USAGE.update({
            'model': model or current_model(),
            'input': getattr(usage, 'input_tokens', None),
            'output': getattr(usage, 'output_tokens', None),
            'cache_write': getattr(usage, 'cache_creation_input_tokens', None),
            'cache_read': getattr(usage, 'cache_read_input_tokens', None),
        })
    text = "".join(getattr(b, "text", "") for b in response.content
                   if getattr(b, "type", None) == "text")

    # An answer made entirely of thinking blocks is empty text, and saving
    # that produced a blank reading that had already been paid for. Fail
    # loudly instead: the caller must not cache nothing.
    if not text.strip():
        stop = getattr(response, "stop_reason", None)
        raise ProviderError(
            f"{model or current_model()} returned no text"
            + (f" (stop_reason: {stop})" if stop else "")
            + ". This usually means the whole token budget went on "
              "thinking. Raise LLM_MAX_TOKENS, lower LLM_EFFORT, or ask "
              "a shorter question."
        )
    return text


# ------------------------------------------------------------------ gemini

def _generate_gemini(system, messages, max_tokens, model=None):
    # Configuration before import, for the same reason as the Anthropic path.
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise ProviderError(
            "GEMINI_API_KEY is not set. Get a free key at aistudio.google.com/apikey."
        )

    try:
        from google.genai import types
        client = _gemini_client(key)
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

    try:
        response = client.models.generate_content(
            model=model or current_model(),
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
            ),
        )
    except Exception as e:
        raise _readable_provider_failure(e, model or current_model())

    meta = getattr(response, 'usage_metadata', None)
    LAST_USAGE.clear()
    LAST_USAGE.update({
        'model': model or current_model(),
        'input': getattr(meta, 'prompt_token_count', None) if meta else None,
        'output': getattr(meta, 'candidates_token_count', None) if meta else None,
        'cache_write': None,
        'cache_read': getattr(meta, 'cached_content_token_count', None) if meta else None,
    })

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


def generate(system, messages, max_tokens=None, model=None):
    """
    Ask a provider for one completion.

    system:   the full system prompt (personas + shared rules)
    messages: [{"role": "user"|"assistant", "content": str}, ...] — the entire
              conversation, sent in full every call
    model:    optional, one of CHOICES. Anything not on that list is
              refused rather than passed through: the value arrives from
              the browser, and an unchecked string would let a caller
              bill this account against any model the key can reach.
    """
    provider = PROVIDER
    if model:
        choice = BY_ID.get(model)
        if not choice:
            raise ProviderError(f"Unknown model {model!r}.")
        if not provider_available(choice['provider']):
            raise ProviderError(
                f"{choice['label']} needs a "
                f"{choice['provider'].upper()}_API_KEY, which is not set "
                f"on this server."
            )
        provider = choice["provider"]

    backend = _BACKENDS.get(provider)
    if backend is None:
        raise ProviderError(
            f"Unknown provider {provider!r}. "
            f"Expected one of: {', '.join(sorted(_BACKENDS))}."
        )
    return backend(system, messages, max_tokens or MAX_OUTPUT_TOKENS, model)
