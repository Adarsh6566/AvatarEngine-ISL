"""English → ISL gloss, using a language model as a constrained selector.

WHAT THIS REPLACES
------------------
The signer page matches text to signs by exact string lookup over a small table
of surface forms. That fails on anything it was not spelled out for: "thanked"
and "thanks a lot" miss THANK_YOU, "greetings" misses HELLO, "how's it going"
misses HOW_ARE_YOU. Every miss is silently dropped, so the avatar simply says
less than it could.

A model handles the parts a lookup table cannot: morphology, synonyms, and the
fact that ISL word order is not English word order — it is topic-comment, with
no copula and no articles, so "How are you today?" is not a word-for-word
mapping onto signs.

WHY THIS CANNOT INVENT A SIGN
-----------------------------
The model is never asked to produce sign language. It is given the caller's
vocabulary and asked to choose from it and put the choices in order — selection
over a closed set, not generation. Two things enforce that:

  * the vocabulary is supplied per request by the client that owns it, so this
    module has no sign list of its own to drift out of date, and
  * every gloss the model returns is checked against that vocabulary and
    dropped if absent.

So the worst a bad completion can do is return fewer signs, or the wrong ones
from the real set. It can never conjure motion the avatar does not have.

FAILURE IS NOT AN ERROR
-----------------------
No API key, no network, a timeout, a malformed completion — all of these return
None, and the caller falls back to its existing string matcher. Translation is
an improvement on the matcher, not a dependency of it; a signer page that stops
signing because a language API is unreachable would be a worse page than the one
that existed before.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional, Sequence

import httpx

# --- providers ---------------------------------------------------------------
#
# Two backends, because the requirement here is unusual: the task is constrained
# SELECTION over a handful of glosses, not open generation, and a 4B model run
# locally is entirely capable of it. That makes a hosted API optional rather
# than necessary — which matters for a project aimed at students, where a
# per-phrase API bill is a real deployment problem and an API key is a real
# operational one.
#
# GLOSS_PROVIDER: "auto" (default), "anthropic", or "ollama".
#   auto -> Anthropic when a key exists, else Ollama when it answers, else off.

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
# Measured on the nine-sign vocabulary over ten sentences: qwen3:8b scored
# 10/10, qwen3:4b 9/10 — and at the same ~750ms, because the reply is a few
# tokens and both stay resident in 8.5GB of VRAM, so the cost is prompt
# processing rather than generation. The larger model is free here.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

# Short: the reply is a handful of glosses. A long ceiling only delays the
# fallback when something goes wrong.
TIMEOUT_SECONDS = 8.0
MAX_TOKENS = 200

# Most signs a single transcript segment may emit before it is treated as the
# model listing the vocabulary rather than translating. Deliberately generous:
# real speech reaching four distinct greetings inside one segment is rare, and
# the playback timeline could not show them anyway.
MAX_GLOSSES_PER_SEGMENT = 3


@dataclass(frozen=True)
class VocabEntry:
    gloss: str
    words: Sequence[str]


def _ollama_reachable() -> bool:
    try:
        return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5).status_code == 200
    except Exception:
        return False


def provider() -> Optional[str]:
    """Which backend will serve a request, or None when translation is off."""
    choice = os.environ.get("GLOSS_PROVIDER", "auto").lower()
    if choice == "anthropic":
        return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else None
    if choice == "ollama":
        return "ollama" if _ollama_reachable() else None
    # auto: a configured key wins, since it was a deliberate act; otherwise fall
    # to whatever is running locally, which costs nothing.
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "ollama" if _ollama_reachable() else None


def available() -> bool:
    """Whether any provider can serve a request. Never logs a key."""
    return provider() is not None


def _prompt(text: str, vocabulary: Sequence[VocabEntry]) -> str:
    listing = "\n".join(f"  {v.gloss} — {', '.join(v.words)}" for v in vocabulary)
    return f"""You are translating English into Indian Sign Language gloss.

The avatar can perform ONLY these signs. Each line is a gloss followed by
English words it covers:

{listing}

Translate the sentence below into a sequence of these glosses.

Rules:
- Output ONLY glosses from the list above. Never invent one.
- Follow ISL structure, not English: no copula ("is", "are"), no articles
  ("a", "the"), and time or topic first where it applies.
- Match meaning, not spelling: inflections and synonyms of a listed word should
  map to its gloss ("thanked" and "thanks a lot" are both THANK_YOU).
- Omit anything the vocabulary cannot express. A shorter accurate sequence is
  better than padding it with an approximate sign.
- NEVER add a sign for something the sentence does not actually say. If there is
  no greeting in it, do not output a greeting; if no time of day is mentioned,
  do not output one. A missing sign is a small loss; a sign the speaker never
  said is the avatar putting words in their mouth, which is worse.
- If nothing in the sentence can be signed, return an empty list.

Reply with JSON only, no prose: {{"glosses": ["GLOSS_A", "GLOSS_B"]}}

Sentence: {text}"""


def _ask_anthropic(prompt: str, max_tokens: int = MAX_TOKENS) -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    response = httpx.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    return "".join(
        b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"
    )


def _ask_ollama(prompt: str, max_tokens: int = MAX_TOKENS) -> Optional[str]:
    response = httpx.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            # Constrains decoding to valid JSON, which removes the most common
            # local-model failure — a correct answer wrapped in explanation.
            "format": "json",
            # Reasoning models are the default locally now, and Ollama routes
            # their chain-of-thought into a separate `thinking` field — leaving
            # `response` EMPTY once the token budget is spent reasoning. Every
            # translation came back None until this was turned off. Selecting
            # from nine options needs no deliberation anyway, and disabling it
            # is also several times faster.
            "think": False,
            # Deterministic: the same sentence should not sign differently on
            # two runs, and nothing creative is being asked for here.
            "options": {"temperature": 0, "num_predict": max_tokens},
        },
        # Local generation on a cold model can take longer than a hosted call,
        # and the first request also pays for loading weights onto the GPU.
        timeout=TIMEOUT_SECONDS * 4,
    )
    response.raise_for_status()
    body = response.json()
    # Prefer the answer; fall back to the thinking text only if a model ignores
    # think=False, so a stray reasoning model still yields something parseable.
    return body.get("response") or body.get("thinking") or ""


def translate(text: str, vocabulary: Sequence[VocabEntry]) -> Optional[list[str]]:
    """Glosses for `text`, or None if translation was not possible.

    None means "use your fallback" and is returned for every failure mode. The
    caller cannot distinguish a missing key from a timeout from a bad
    completion, and should not need to: the response is the same either way.
    """
    if not text.strip() or not vocabulary:
        return None
    which = provider()
    if which is None:
        return None

    prompt = _prompt(text, vocabulary)
    try:
        reply = _ask_anthropic(prompt) if which == "anthropic" else _ask_ollama(prompt)
    except Exception as e:
        print(f"[gloss] {which} unavailable, falling back: {type(e).__name__}: {e}")
        return None
    if not reply:
        return None

    return _parse(reply, vocabulary)


def _parse(reply: str, vocabulary: Sequence[VocabEntry]) -> Optional[list[str]]:
    """Pull the gloss list out of a completion and drop anything not ours.

    Models wrap JSON in prose or fences often enough that locating the object by
    its braces is more reliable than trusting the whole reply to parse.
    """
    # Reasoning models (qwen3 among them) prepend a <think> block, and any
    # braces inside it would capture the brace scan below before the answer.
    if "</think>" in reply:
        reply = reply.split("</think>", 1)[1]

    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return None

    raw = parsed.get("glosses")
    if not isinstance(raw, list):
        return None

    # The guarantee: nothing survives that the caller did not offer.
    known = {v.gloss for v in vocabulary}
    kept = [g for g in raw if isinstance(g, str) and g in known]
    dropped = [g for g in raw if g not in kept]
    if dropped:
        print(f"[gloss] discarded glosses outside the vocabulary: {dropped}")
    return kept

# --- batch ------------------------------------------------------------------
#
# A lecture is not a phrase. Seventeen minutes of speech transcribes to 176
# segments, so four hours is roughly 2,500 — and at ~750ms each, translating
# them one at a time would take half an hour before the avatar could sign
# anything. Batching amortises the prompt (the vocabulary listing is the bulk
# of it and is identical every time) across many sentences.


def _batch_prompt(texts: Sequence[str], vocabulary: Sequence[VocabEntry]) -> str:
    listing = "\n".join(f"  {v.gloss} — {', '.join(v.words)}" for v in vocabulary)
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    return f"""You are translating English into Indian Sign Language gloss.

The avatar can perform ONLY these signs. Each line is a gloss followed by
English words it covers:

{listing}

Translate EACH numbered sentence below into a sequence of these glosses.

Rules:
- Output ONLY glosses from the list above. Never invent one.
- Follow ISL structure, not English: no copula, no articles.
- Match meaning, not spelling: inflections and synonyms of a listed word map to
  its gloss ("thanked" and "thanks a lot" are both THANK_YOU).
- That cuts both ways: sharing letters is not sharing meaning. Before choosing a
  gloss, ask whether the speaker is actually doing that thing — greeting,
  thanking, asking after someone. If they are not, the sign does not belong.
- NEVER add a sign for something a sentence does not actually say. A missing
  sign is a small loss; a sign the speaker never said is the avatar putting
  words in their mouth, which is worse.
- Translate what the speaker SAYS, never what they are talking about. A lecture
  about greetings is full of sentences that mention greetings without
  containing one — "let's look at some common phrases", "which greeting would
  you use here", "these are used at different times of day". None of those is a
  greeting. They get an empty list. Only sign a greeting when the speaker is
  actually greeting someone.
- If a sentence genuinely contains nothing this vocabulary can express, return
  an empty list for it. Do not stretch to fill it.
- But DO translate what is there. A greeting or a thanks buried mid-sentence
  still counts, and phrasing that merely differs from the listed words ("how are
  you all doing" for HOW_ARE_YOU) is a match, not a miss.
- Return one entry per sentence, keeping the numbers.

Reply with JSON only, no prose:
{{"results": [{{"n": 1, "glosses": ["GLOSS_A"]}}, {{"n": 2, "glosses": []}}]}}

Sentences:
{numbered}"""


def translate_batch(
    texts: Sequence[str], vocabulary: Sequence[VocabEntry]
) -> Optional[list[list[str]]]:
    """Glosses for each text, aligned by index, or None if unavailable.

    The result is always the same length as `texts`. A sentence the model
    skipped comes back as an empty list rather than shifting everything after it
    — misalignment here would sign the wrong phrase at the wrong timestamp,
    which is worse than signing nothing.
    """
    if not texts or not vocabulary:
        return None
    which = provider()
    if which is None:
        return None

    prompt = _batch_prompt(texts, vocabulary)
    try:
        # Output scales with the batch, unlike the single case.
        reply = (
            _ask_anthropic(prompt, max_tokens=60 * len(texts) + 200)
            if which == "anthropic"
            else _ask_ollama(prompt, max_tokens=60 * len(texts) + 200)
        )
    except Exception as e:
        print(f"[gloss] {which} batch failed, falling back: {type(e).__name__}: {e}")
        return None
    if not reply:
        return None

    return _parse_batch(reply, vocabulary, len(texts))


def _parse_batch(
    reply: str, vocabulary: Sequence[VocabEntry], expected: int
) -> Optional[list[list[str]]]:
    if "</think>" in reply:
        reply = reply.split("</think>", 1)[1]
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return None

    rows = parsed.get("results")
    if not isinstance(rows, list):
        return None

    known = {v.gloss for v in vocabulary}
    # Indexed by the model's own numbering rather than by position, so a dropped
    # or reordered entry cannot shift its neighbours onto the wrong sentence.
    out: list[list[str]] = [[] for _ in range(expected)]
    for row in rows:
        if not isinstance(row, dict):
            continue
        n = row.get("n")
        glosses = row.get("glosses")
        if not isinstance(n, int) or not 1 <= n <= expected or not isinstance(glosses, list):
            continue
        kept = [g for g in glosses if isinstance(g, str) and g in known]
        out[n - 1] = _reject_dump(kept, len(vocabulary))
    return out


def _reject_dump(glosses: list[str], vocab_size: int) -> list[str]:
    """Drop a result that is the vocabulary being listed rather than translated.

    The characteristic failure of a small model on this task is not inventing a
    sign — the vocabulary check already stops that — but emitting MOST OF THE
    LIST when a sentence merely mentions the topic. Measured on a real lesson:
    "let's look at some common phrases" produced all eight signs, "which
    greeting would you use here" six.

    Two independent reasons to refuse those:

      * A transcript segment is a couple of seconds of speech and cannot
        actually contain six distinct greetings.
      * Even if it could, each captured sign takes ~2.44s to perform, so a 2.6s
        window can show one. Six is not a translation the timeline can play.

    The whole entry is dropped rather than truncated. A dump's ORDER carries no
    meaning, so keeping the first few would still sign things the speaker never
    said — and nobody reviews this before a deaf student sees it.
    """
    if len(glosses) > MAX_GLOSSES_PER_SEGMENT or len(glosses) > vocab_size // 2:
        print(f"[gloss] rejected vocabulary dump ({len(glosses)} signs): {glosses}")
        return []
    return glosses
