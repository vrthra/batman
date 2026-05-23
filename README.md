# Batman

Batman is a coverage-guided input generator that discovers valid inputs for a target program
by combining a priority-queue-driven prefix search,
a genetic algorithm over suffixes,
and binary-search-based suffix minimisation.
It requires no grammar or format specification;
all guidance comes from LLVM source-based coverage instrumentation.

## Overview

The core idea is to build valid inputs character by character,
guided by how much each addition changes the program's coverage.
A **prefix** is a string that has been partially explored.
A **suffix** is a candidate continuation appended to a prefix for testing.
When a prefix plus a suffix causes the program to execute more code than the prefix alone,
that is a signal that the suffix is pushing the parser further into its state machine.
Batman exploits this signal to grow prefixes toward complete, accepted inputs.

## Components

### 1. Coverage measurement (`handle_coverage.sh`, `get_instructions`)

Every candidate string is run through `handle_coverage.sh`,
which instruments the binary with `LLVM_PROFILE_FILE`, merges the raw profile data with
`llvm-profdata`, and exports a JSON coverage report with `llvm-cov`.
The coverage score is the sum of execution counts across all source regions in that report.
A higher score means more code was exercised.

Each worker process uses a unique per-PID temp file path (`/tmp/batman_<pid>.json`)
so that parallel runs do not collide on the coverage files.

### 2. Suffix population and genetic algorithm (`SuffixPopulation`)

Batman maintains an evolving population of suffix strings.
The initial population of `SAMPLE_COUNT²` individuals is generated using a
three-level structure:

- **Level 1** (`charset_1`): one category-weighted character drawn from `CHARSET_1_CATEGORIES`
- **Level 2** (`charset_2`): one category-weighted character drawn from `CHARSET_2_CATEGORIES`
- **Level 3** (`get_expanded_string`): 64 uniformly random printable characters

Both character sets use the same seven categories with equal category probability,
preventing large groups (letters, digits) from drowning out smaller ones (brackets, quotes,
punctuation):

| Category | Characters |
|---|---|
| Digits | `0-9` |
| ASCII letters | `a-z A-Z` |
| Opening brackets | `( { [ <` |
| Closing brackets | `) } ] >` |
| Quotes | `" ' \`` |
| Whitespace | space, tab, newline, etc. |
| Other punctuation | `! # $ % & * + , - . / : ; = ? @ \ ^ _ \| ~` |

Up to `BANK_PERCENTAGE` (50%) of the initial population is seeded from the **suffix bank**
— a set of previously discovered high-performing suffixes — prepended with a fresh
`charset_1()` character.
The remainder is generated fresh using the three-level structure.

After each round of suffix evaluation, the population evolves:

1. **Fitness update**: each evaluated suffix receives a fitness score from the active
   fitness function.
2. **Elitism**: the top 10% of individuals by fitness are carried into the next generation
   unchanged.
3. **Tournament selection**: the remaining slots are filled by selecting parents via
   tournaments of size 5.
4. **Single-point crossover**: two parents are recombined at a random split point.
5. **Mutation**: each character in the child is replaced with a random printable character
   at a 5% per-character rate.

#### Fitness functions

The fitness function is selected by setting `FITNESS_FUNCTION`:

- **`max_count`** (default): fitness = 1.0 if the suffix caused any coverage increase,
  0.0 otherwise.
  Maximises the number of productive suffixes in the population.
- **`max_length`**: fitness = length of the minimised best suffix if it caused a coverage
  increase, 0.0 otherwise.
  Pushes the population toward longer, structurally richer suffixes.

### 3. Suffix minimisation (`minimise_suffix`)

For each `(prefix, suffix)` pair, `minimise_suffix` binary-searches for the shortest
prefix of the suffix that still achieves the maximum observed coverage difference relative
to running the program on the prefix alone:

1. Compute baseline coverage for `prefix`.
2. Compute coverage for `prefix + full_suffix`; set `best_diff`.
3. Binary-search over suffix lengths from 0 to `len(suffix)`,
   keeping the shortest length whose coverage diff is `>= best_diff`.
4. If a candidate achieves zero diff and is not a complete parse, stop early.
5. Any candidate that causes the program to exit 0 is collected in `accepted`.

The return value is `(accepted, best_suffix, best_diff)`.

### 4. Prefix priority queue (`PrefixEntry`, `create_valid_strings`)

Batman maintains a dict of unique `PrefixEntry` objects keyed by prefix string.
Each entry tracks:

- **`priority`**: an integer (may be negative); lower values are explored first.
  Computed after every `generate()` call by the active priority function (see below).
- **`remaining`**: the set of first characters not yet seen among the sampled suffixes for
  this prefix.
  When `remaining` is empty the prefix is discarded — all reachable first-character
  continuations have been sampled at least once.
- **`tried_count`**: total number of suffix evaluations across all attempts,
  used to display a cumulative progress counter in the log.
- **`generate_count`**: number of times `generate()` has been called for this prefix,
  used by the `by_length` priority function.
- **`extension_count`**: cumulative number of new child prefixes produced by this prefix,
  used by the `by_extensions_produced` priority function.
- **`depth`**: number of extension steps from the initial seed to this prefix
  (seed = 0, first child = 1, grandchild = 2, …),
  used by the `by_depth` priority function.
- **`boundary_count`**: number of token boundaries crossed in the extension chain from
  the initial seed to this prefix, inherited from the parent at creation time.
  A boundary is counted when the extension that produced this prefix came from a suffix
  trial where binary search successfully shortened the suffix (indicating a token boundary
  was found), or from a complete accepted parse.
  Used by the `by_boundary_count` priority function.

At each iteration the driver:

1. Picks a random entry from the lowest-priority group.
2. Calls `generate()` with that prefix.
3. Updates the entry's priority via the active priority function.
4. Adds any new extensions to the queue (deduplication is free because the queue is a dict).
5. Removes the entry if its `remaining` set is exhausted.

#### Priority functions

The priority function is selected by setting `PRIORITY_FUNCTION`.
All functions receive the current `PrefixEntry`, `n_tried` (suffix evaluations this round),
and `max_instructions` (largest coverage delta seen this round), and return the new priority.

- **`by_extension_count`** (default): priority accumulates the total number of suffix
  minimisations run against this prefix (`priority += n_tried`).
  Entries that have been explored less are always preferred, regardless of prefix length.
- **`by_most_explored`**: the inverse — priority decreases by `n_tried` each round
  (going negative), so the most-explored entries are always preferred.
- **`by_extensions_produced`**: priority = `−extension_count`, where `extension_count`
  is the cumulative number of new child prefixes this prefix has produced.
  Prefers the most productive prefixes — those that have spawned the longest chains of
  extensions — rather than those merely tried most often.
- **`by_depth`**: priority = `−depth`, where `depth` is the number of extension steps
  from the initial seed (fixed at creation time).
  Always prefers the deepest prefix in the extension chain: if `aaaa` → `aaaa1234` →
  `aaaa1234bbbb`, the last entry (depth 2) is always explored before shallower ones.
- **`by_boundary_count`**: priority = `generate_count − boundary_count`, where
  `boundary_count` is inherited from the parent at creation time (each extension step
  that crossed a token boundary adds 1), and `generate_count` increments each time the
  entry is explored.
  An entry with `boundary_count = k` can be explored `k` extra times before tying with a
  fresh entry that has no boundaries, preventing any single prefix from being picked
  indefinitely while still favouring structurally richer prefixes.
- **`by_length`**: priority = `len(prefix) + generate_count`.
  Replicates the original behaviour: shorter prefixes are preferred, and within the same
  length, prefixes tried fewer times are preferred.
- **`by_instruction_count`**: priority accumulates the maximum coverage delta seen each
  round (`priority += max_instructions`).
  Prefixes that repeatedly produce large coverage swings are deferred sooner.

The current state of the queue is written to disk after every change as two JSON files:

- `priority_by_priority.json`: `{ "priority": ["prefix", ...], ... }`
- `priority_by_prefix.json`: `{ "prefix": priority, ... }`

### 5. Extension discovery (`generate`)

`generate(prefix)` samples `SAMPLES_TO_TEST` suffixes from the population,
evaluates each with `minimise_suffix`, and builds extensions for the prefix queue:

- **Bank update**: any suffix that achieved the maximum coverage diff in this batch is
  added to the suffix bank for use in future population initialisation.
- **Extensions from minimised suffixes**: any suffix with a positive coverage diff
  (not just the maximum) contributes `prefix + best_suffix[:1]` — just the first
  character of the minimised suffix — as a new prefix to explore.
  Subsequent characters are discovered step by step through further `generate()` calls,
  so each character that crosses a token boundary earns its own `boundary_count`
  increment rather than the whole suffix arriving in one leap.
- **Extensions from complete strings**: any complete string found during binary search has
  its last character stripped and is added as a prefix.
  For example, if `{"key":42}` is accepted, `{"key":42` is enqueued,
  enabling exploration of complex nested structures.

In serial mode, the loop stops as soon as any suffix produces an accepted complete string.
In parallel mode, all `SAMPLES_TO_TEST` jobs are submitted at once to a
`ProcessPoolExecutor` and all results are collected before proceeding.

Valid inputs are written immediately to `valid_inputs.txt` when found,
one `repr()`-quoted string per line.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PROGRAM` (env) | `./program.out` | Path to the target binary |
| `TMP_JSON` (env) | `/tmp/tmp.json` | Base path for coverage JSON output |
| `IS_PARALLEL` | `True` | Run suffix evaluations in parallel |
| `DISCARD_NON_BOUNDARY_EXTENSIONS` | `True` | If `True`, discard extensions where binary search could not shorten the suffix (no token boundary found), avoiding needless exploration of long single-token strings |
| `ADD_PREFIXES_FROM_ACCEPTED` | `False` | If `True`, enqueue `acc[:-1]` for every accepted (exit-0) string found during minimisation, allowing the search to grow from known-complete inputs |
| `FITNESS_FUNCTION` | `"max_count"` | GA fitness function (`"max_count"` or `"max_length"`) |
| `PRIORITY_FUNCTION` | `"by_extension_count"` | Priority function (`"by_extension_count"`, `"by_most_explored"`, `"by_extensions_produced"`, `"by_depth"`, `"by_boundary_count"`, `"by_length"`, or `"by_instruction_count"`) |
| `SAMPLES_TO_TEST` | `100` | Suffixes sampled per `generate()` call |
| `BANK_PERCENTAGE` | `0.5` | Fraction of initial population seeded from the bank |
| `LENGTH_INCREASE` | `64` | Length of the random tail in each generated suffix |

## Usage

```sh
PROGRAM=./my_program python bin/batman.py
```

The target binary must be compiled with LLVM source-based coverage instrumentation:

```sh
clang -fprofile-instr-generate -fcoverage-mapping -o my_program my_program.c
```

Dependencies: `llvm-profdata`, `llvm-cov` (Linux: `-18` suffix; macOS: via `xcrun`).

## Output

| File | Content |
|---|---|
| `valid_inputs.txt` | One `repr()`-quoted valid input per line, appended as found |
| `priority_by_priority.json` | Priority queue grouped by priority level |
| `priority_by_prefix.json` | Priority queue indexed by prefix string |
