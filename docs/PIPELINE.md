# Translation Pipeline

How free English text becomes an ordered list of gesture ids the avatar can play.

This document covers `backend/` — the recogniser, the mapper, and the translator. Everything here is verified against the running code; the example outputs are real, not illustrative.

---

## 1. The shape of the problem

Text is unbounded. Gestures are a fixed, small set. The pipeline's job is to narrow one into the other without losing meaning along the way, and to do it in a way where each stage can be replaced without disturbing the others.

```
  "Hello please. Thank you!"          unbounded free text
             │
             ▼   ── RECOGNISE ──      structure: sentences, words, distinct set
  ('hello','please','thank','you')
             │
             ▼   ── MAP ──            vocabulary lookup, one per distinct word
  hello→HELLO  please→PLEASE  thank→THANKYOU  you→YOU
             │
             ▼   ── RESOLVE ──        fingerspell whatever did not map
  {hello:[HELLO], please:[PLEASE], ...}
             │
             ▼   ── REPLAY ──         expand in written order
  ['HELLO','PLEASE','THANKYOU','YOU']
```

Each stage does **strictly less work than the one before it**. Recognition is proportional to input length; mapping is proportional to *distinct* words; replay is a pure expansion with no lookups at all.

---

## 2. Stage 1 — Recogniser

`backend/language/recognizer.py`

Splits raw text into three views of the same content, in one pass.

### Recursive splitting

Splitting descends a list of levels, one delimiter per level. Each level cuts the text it is given and recurses on every piece, so the depth of the result equals the number of levels.

```
_LEVELS = (_SENTENCE_BOUNDARY, _WHITESPACE)


 "Hello please. Thank you!"
            │
   level 0  │  split on [.!?\n]+
            ▼
 ┌──────────────────┬──────────────────┐
 │  "Hello please"  │   " Thank you"   │
 └──────────────────┴──────────────────┘
            │                  │
   level 1  │  split on \s+    │
            ▼                  ▼
   ['hello','please']    ['thank','you']
            │                  │
   base     │  normalise each leaf
            ▼                  ▼
        (( 'hello','please' ), ( 'thank','you' ))
```

Adding a level — clauses on commas, say — means adding one entry to `_LEVELS`. The recursion itself never changes.

### The three views

```python
Recognition(
    sentences  = (('hello','please'), ('thank','you')),   # grouped, structure kept
    words      = ('hello','please','thank','you'),        # flat, WRITTEN ORDER
    vocabulary = frozenset({'hello','please','thank','you'}),  # distinct, no order
)
```

| View | Shape | What it is for |
|---|---|---|
| `sentences` | nested tuples | Future use: pauses between sentences, prosody |
| `words` | flat tuple | **Drives playback order.** Duplicates intact |
| `vocabulary` | frozenset | **Drives lookups.** One entry per distinct word |

The split between `words` and `vocabulary` is the central idea of the whole pipeline: *resolve against the set, replay against the list.*

### Why raw text

`recognize()` takes **raw** text, not normalised text. `TextNormalizer` strips punctuation — including the `.!?` that sentence splitting depends on. So normalisation happens per word, *after* splitting.

```
  WRONG                                  RIGHT
  normalize("Hi. Bye.")                  split("Hi. Bye.")
    → "hi bye"                             → (('hi',), ('bye',))
    → sentence boundary destroyed          → normalise each leaf
```

### Two entry points

```python
recognize(text) -> set[str]      # stores ordered words, returns distinct set
last()          -> Recognition   # retrieve what was stored
split(text)     -> Recognition   # pure, stateless, returns all three views
```

`recognize()`/`last()` is the stateful pair. Because `recognizer` is a module-level singleton, two concurrent requests can overwrite each other's stored words — **prefer `split()` under load.**

---

## 3. Stage 2 — Mapper

`backend/mapper.py` · vocabulary in `backend/vocabulary.json`

Resolves words to gestures, deduplicating the work.

### Resolve unique, replay ordered

```
  words:  please  please  please  please  please      5 words
                        │
                        ▼  vocabulary = {'please'}
             map_vocabulary()  ──►  1 lookup          ← bounded by vocabulary,
                        │                                not by input length
                        ▼  {'please': 'PLEASE'}
             map_sequence()   ──►  0 lookups
                        │
                        ▼
  [please:PLEASE] [please:PLEASE] [please:PLEASE] [please:PLEASE] [please:PLEASE]
```

`map_sequence()` performs **no lookups of its own**. It replays the vocabulary result into written order. That is the entire point of the two-function split.

### Why two different shapes

```python
Mapping(
    vocabulary = {'you': 'YOU', 'me': 'ME'},                    # dict
    sequence   = [MappedWord('you','YOU'), MappedWord('you','YOU'),
                  MappedWord('me','ME')],                       # list of pairs
)
```

`vocabulary` is a `dict` because distinct keys cannot repeat. `sequence` **cannot** be a dict — `"you you me"` would collapse two `you` entries into one and silently lose a sign. Hence a list of `MappedWord(word, gesture)` pairs.

### `UNMAPPED` vs `UNKNOWN`

```python
DEFAULT_GESTURE = "UNMAPPED"
```

Deliberately not `UNKNOWN`. The two mean different things:

| Value | Meaning |
|---|---|
| `UNKNOWN` | The input could not be understood at all |
| `UNMAPPED` | The word was understood fine — we simply have no gesture for it |

Only `UNMAPPED` is recoverable, and stage 3 recovers it. Collapsing them would make the fallback impossible to trigger.

### Worked example

Input: `"Hello please. Thank you! You help me, me too."`

```
9 words ──► 7 lookups                    ordered sequence (9 entries)
  hello   → HELLO                          [hello  : HELLO   ]
  help    → UNMAPPED                       [please : PLEASE  ]
  me      → ME                             [thank  : THANKYOU]
  please  → PLEASE                         [you    : YOU     ]
  thank   → THANKYOU                       [you    : YOU     ]   ← duplicate kept
  too     → UNMAPPED                       [help   : UNMAPPED]
  you     → YOU                            [me     : ME      ]
                                           [me     : ME      ]   ← duplicate kept
                                           [too    : UNMAPPED]
```

---

## 4. Stage 3 — Translator

`backend/language/translator.py` · alphabet in `backend/language/alphabet.json`

Handles the `UNMAPPED` case by fingerspelling, so an unknown word degrades instead of vanishing.

### The problem it solves

Without a fallback, any word outside `vocabulary.json` — a name, a place, ordinary vocabulary we have no clip for — disappears from the output entirely. `"Sorry Adarsh"` would sign only `SORRY`, and the person being addressed is lost. **Context loss, silently.**

### Fingerspelling, two stages

`spell()` mirrors the mapper's shape one level down, at character scale:

```
   "hello"  ── UNMAPPED, fall back to spelling
       │
       ▼   regex [a-z0-9]  →  ['h','e','l','l','o']
       │
   STAGE 1  distinct chars {h,e,l,o} → 4 lookups     ← same dedup trick;
       │                                               the repeated 'l'
       ▼   replay in order, duplicates intact          costs one lookup
   [h:A] [e:E] [l:L] [l:L] [o:O]
       │
   STAGE 2  bundle into one list for the word
       │
       ▼
   {hello: ['A','E','L','L','O']}
```

That bundle then **replaces** `hello: UNMAPPED` in the resolved vocabulary.

### Uniform shape is what makes it work

Every word resolves to a `Resolution` carrying a **list** of gestures, whether mapped or spelled:

```
  mapped   →  'please' : Resolution(['PLEASE'], spelled=False)
  spelled  →  'help'   : Resolution(['H','E','L','P'], spelled=True)
```

Because both are lists, the replay step never branches on which happened:

```python
for word in recognition.words:
    gloss.extend(resolved[word].gestures)
```

One line handles both cases. Adding a third resolution strategy later — a synonym table, a compound-sign matcher — requires no change here at all, as long as it also returns a `Resolution`.

`spelled` is **recorded** at the moment the decision is made, not inferred afterwards from the shape of `gestures`. A one-letter word like `"a"` spells to a single gesture, so length alone cannot distinguish it from a mapped word.

### Segments — grouping for the UI

`segment(text)` returns one `Segment` per word rather than a flat list:

```python
Segment(word='help', gestures=['H','E','L','P'], spelled=True)
```

The frontend needs this to caption playback. A flat list cannot say where one spelled word ends and the next begins:

```
  flat     "banana apple" → [B,A,N,A,N,A,A,P,P,L,E]   ← where is the boundary?
  segments               → [banana: B,A,N,A,N,A]
                           [apple : A,P,P,L,E]         ← recoverable
```

`translate()` is derived from `segment()` by flattening, so the two views can never disagree.

### Worked example

```
Input:  "please help me"

  resolve_vocabulary
    please  MAPPED   ['PLEASE']
    help    SPELLED  ['H','E','L','P']
    me      MAPPED   ['ME']

  replay in written order: please → help → me

Output: ['PLEASE','H','E','L','P','ME']
```

---

## 5. End to end

Real responses from `POST /translate`:

```
  "hello"                     →  ["HELLO"]
  "yes yes no"                →  ["YES","YES","NO"]
  "Hello please. Thank you!"  →  ["HELLO","PLEASE","THANKYOU","YOU"]
  "please help me"            →  ["PLEASE","H","E","L","P","ME"]
  "banana"                    →  ["B","A","N","A","N","A"]
  "12 dogs"                   →  ["1","2","D","O","G","S"]  (digits caption-only until .vrma exists — P1-1 leave-as-is)
  ""                          →  []
```

Note what is **absent**: no `UNKNOWN`, no `UNMAPPED`. Neither reaches the output any more.

### Call graph

```
  app.py  POST /translate
     │
     └─► translator.translate(text)
            │
            ├─► recognizer.split(text) ─────────────► Recognition
            │                                          (sentences, words, vocabulary)
            ├─► resolve_vocabulary(recognition)
            │      │
            │      ├─► mapper.map_recognition(rec) ──► Mapping
            │      │      ├─ map_vocabulary()           vocabulary.json
            │      │      └─ map_sequence()
            │      │
            │      └─► spell(word)  for each UNMAPPED  alphabet.json
            │
            └─► replay words in order ──────────────► list[str]
```

---

## 6. Data files

| File | Maps | Consulted |
|---|---|---|
| `backend/vocabulary.json` | word → gesture id | Every distinct word, once |
| `backend/language/alphabet.json` | character → atomic gesture | Only for `UNMAPPED` words |
| `backend/language/dictionary.json` | — | **Orphaned.** Superseded by `vocabulary.json` |

Both live dictionaries are loaded **once at import**, into module-level dicts. No request ever touches the disk.

---

## 7. Extending it

| To add… | Change | Ripples |
|---|---|---|
| A new word or synonym | one line in `vocabulary.json` | none |
| A new split level (clauses) | one entry in `_LEVELS` | none |
| A different fallback strategy | new branch in `resolve_vocabulary()` | none, if it returns a list |
| Real NLP / an LLM translator | replace `translate()` internals | none — the HTTP contract holds |

The contract that makes this true:

```
  POST /translate   {"text": str}  →  {"gloss": [str],
                                       "segments": [{word, gestures, spelled}]}
```

`gloss` has been a flat `list[str]` through every redesign in this document. `segments` was added later, **additively** — clients that only want a playback list are unaffected, while clients that caption playback get the word grouping they need.

---

## 8. Known gaps

- **No digit assets.** `A`–`Z` have `.vrma` clips; `0`–`9` resolve correctly but have no `.vrma` yet (P1-1 leave-as-is — sequencer holds caption-only). Fingerspelling for letters is complete; digits are logically complete and visually inert until those 10 clips are authored.
- **Concurrency.** `recognize()`/`last()` stores state on a module-level singleton. Use `split()` under real load.
- **No multi-word phrases.** Splitting is word-level, so `"thank you"` signs as `THANKYOU` + `YOU` rather than a single unit. N-gram recombination would belong in the mapper.
- **Layering.** `language/translator.py` imports the parent-level `mapper.py`, so the language layer depends on the gesture layer. Intentional, but worth knowing.
- **`backend/language/` has no `__init__.py`** and works as a namespace package. Fine today; breaks if the app is ever packaged or run from another working directory.
