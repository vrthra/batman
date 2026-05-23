#!/usr/bin/env python3
# coding: utf-8

import json
import os
import random
import string
import subprocess
from concurrent.futures import ProcessPoolExecutor

LENGTH_INCREASE = 64

BANK_PERCENTAGE = 0.5  # fraction of each inner batch drawn from SUFFIXES (the suffix bank) instead of generated randomly
IS_PARALLEL = True
FITNESS_FUNCTION = "max_count"  # "max_count" | "max_length"
PRIORITY_FUNCTION = "by_boundary_count"  # "by_length" | "by_extension_count" | "by_most_explored" | "by_extensions_produced" | "by_depth" | "by_boundary_count" | "by_instruction_count"
DISCARD_NON_BOUNDARY_EXTENSIONS = (
    True  # if True, only enqueue extensions where binary search found a shorter suffix
)
ADD_PREFIXES_FROM_ACCEPTED = False  # if True, enqueue acc[:-1] for every accepted (exit-0) string found during minimisation

MY_PROGRAM = os.environ.get("PROGRAM", "./program.out").strip()
tmp_JSON = os.environ.get("TMP_JSON", "/tmp/tmp.json").strip()
PREFIX = os.environ.get("PREFIX", "")

CHARSET = list(string.printable)
SAMPLE_COUNT = len(CHARSET)
SAMPLES_TO_TEST = 100

_BRACKETS_OPEN = list("({[<")
_BRACKETS_CLOSE = list(")}]>")
_QUOTES = list("\"'`")
_OTHER_PUNCT = list(set(string.punctuation) - set("({[<)}]>") - set("\"'`"))

# Charset categories; each category has equal selection probability,
# and within a category every character has equal probability — this prevents the
# large letter/digit groups from drowning out the smaller punctuation groups
_CATEGORIES = [
    list(string.digits),
    list(string.ascii_letters),
    _BRACKETS_OPEN,
    _BRACKETS_CLOSE,
    _QUOTES,
    list(string.whitespace),
    _OTHER_PUNCT,
]

CHARSET_1_CATEGORIES = _CATEGORIES
CHARSET_2_CATEGORIES = _CATEGORIES

# suffixes is the bank of suffix strings found to cause large coverage differences
SUFFIXES = set()
FOUND = set()
POPULATION = None  # SuffixPopulation, initialised in __main__


def pause():
    ...
    # input()


def _fitness_max_count(best_diff: int, best_suffix: str) -> float:
    return 1.0 if best_diff > 0 else 0.0


def _fitness_max_length(best_diff: int, best_suffix: str) -> float:
    return float(len(best_suffix)) if best_diff > 0 else 0.0


_FITNESS_FNS = {
    "max_count": _fitness_max_count,
    "max_length": _fitness_max_length,
}


def _priority_by_length(entry, n_tried: int, max_instructions: int) -> int:
    return len(entry.prefix) + entry.generate_count


def _priority_by_extension_count(entry, n_tried: int, max_instructions: int) -> int:
    return entry.priority + n_tried


def _priority_by_most_explored(entry, n_tried: int, max_instructions: int) -> int:
    return entry.priority - n_tried


def _priority_by_extensions_produced(entry, n_tried: int, max_instructions: int) -> int:
    return -entry.extension_count


def _priority_by_depth(entry, n_tried: int, max_instructions: int) -> int:
    return -entry.depth


def _priority_by_boundary_count(entry, n_tried: int, max_instructions: int) -> int:
    return entry.generate_count - entry.boundary_count


def _priority_by_instruction_count(entry, n_tried: int, max_instructions: int) -> int:
    return entry.priority + max_instructions


_PRIORITY_FNS = {
    "by_length": _priority_by_length,
    "by_extension_count": _priority_by_extension_count,
    "by_most_explored": _priority_by_most_explored,
    "by_extensions_produced": _priority_by_extensions_produced,
    "by_depth": _priority_by_depth,
    "by_boundary_count": _priority_by_boundary_count,
    "by_instruction_count": _priority_by_instruction_count,
}


class SuffixPopulation:
    MUTATION_RATE = 0.05
    ELITE_FRACTION = 0.1
    TOURNAMENT_SIZE = 5

    def __init__(self, individuals: list[str]):
        self._pop: list[tuple[str, float]] = [(s, 0.0) for s in individuals]

    def sample(self, n: int) -> list[str]:
        return [s for s, _ in random.sample(self._pop, min(n, len(self._pop)))]

    def update_fitness(self, results: list[tuple[str, int, str]]):
        # orig_suffix, accepted, best_suffix, best_diff in results:
        scores = {s: _FITNESS_FNS[FITNESS_FUNCTION](bd, bs) for s, a, bs, bd in results}
        self._pop = [(s, scores.get(s, f)) for s, f in self._pop]

    def evolve(self):
        n = len(self._pop)
        sorted_pop = sorted(self._pop, key=lambda x: x[1], reverse=True)
        elite_n = max(1, int(n * self.ELITE_FRACTION))
        new_pop = list(sorted_pop[:elite_n])
        while len(new_pop) < n:
            p1 = self._select()
            p2 = self._select()
            child = self._mutate(self._crossover(p1, p2))
            new_pop.append((child, 0.0))
        self._pop = new_pop

    def _select(self) -> str:
        candidates = random.sample(self._pop, min(self.TOURNAMENT_SIZE, len(self._pop)))
        return max(candidates, key=lambda x: x[1])[0]

    def _crossover(self, s1: str, s2: str) -> str:
        if not s1 or not s2:
            return s1 or s2
        point = random.randint(0, min(len(s1), len(s2)))
        return s1[:point] + s2[point:]

    def _mutate(self, s: str) -> str:
        return "".join(
            random.choice(CHARSET) if random.random() < self.MUTATION_RATE else c
            for c in s
        )

    def __len__(self) -> int:
        return len(self._pop)


# Wraps text in ANSI escape codes for the given color name; returns plain text if color is unknown
def toc(text, color):
    color_codes = {
        "black": "\033[30m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "white": "\033[37m",
        "reset": "\033[0m",  # Resets the color to default
    }

    if color.lower() in color_codes:
        return f"{color_codes[color.lower()]}{text}{color_codes['reset']}"
    else:
        return text


# Parses the llvm-cov JSON report at json_file and sums the execution counts (field index 4)
# across all regions of all functions; returns None if the total is zero (no coverage recorded)
def extract_blocks_from_json(json_file: str | None = None) -> int | None:
    data = json.load(open(json_file or tmp_JSON))

    total = 0
    for f in data["data"][0]["functions"]:
        for b in f.get("regions", []):
            total += b[4]

    return total if total > 0 else None


# Run perf and extract instruction count
# Runs the target program under handle_coverage.sh with input_string fed via stdin,
# then reads the coverage count from the JSON report written by that script
def get_instructions(input_string: str, log_level: int = 0) -> tuple[int | None, int]:
    cmd = [
        "bash",
        "bin/handle_coverage.sh",
        MY_PROGRAM,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5, input=input_string
        )
        instructions = extract_blocks_from_json()
        if instructions is None:
            raise Exception(
                f"Could not parse instruction count for {repr(input_string)}"
            )
    except subprocess.TimeoutExpired:
        if log_level:
            print("Command timed out")
        return None, -1
    except Exception as e:
        if log_level:
            print(f"Error running command: {e}")
        return None, -1
    return instructions, result.returncode


# Runs the program on input_str and classifies the outcome as "complete" (exit 0), "wrong"
# (positive exit code), or "unexpected" (negative exit code, timeout, or other error).
# Returns a 3-tuple of (status, coverage_count, return_code).
def validate_prog(input_str, log_level: int = 0) -> tuple[str, int, int]:
    instructions, ret_code = get_instructions(input_str)
    if ret_code == 0:
        return "complete", instructions or -1, ret_code
    elif ret_code > 0:  # incorrect
        return "wrong", instructions or -1, ret_code
    else:  # signal
        return "unexpected", -1, ret_code


def get_expanded_string(expand_length: int = LENGTH_INCREASE) -> str:
    return "".join(
        random.choice(random.choice(_CATEGORIES)) for _ in range(expand_length)
    )


# Prints a color-coded summary line for curr_str based on the program result rv
# "complete" is green (newline), "incomplete" is yellow (newline), "wrong" is red (overwritten via \r)
def log_program_result(curr_str, rv: str, n: int, c: int, suffix_count: str) -> None:
    if rv == "complete":
        overprint(
            "[%s]\t%s instr=%d, exit=%s. Input string is %s"
            % (suffix_count, rv, n, c, toc(repr(curr_str), "green"))
        )
    elif rv == "unexpected":
        overprint(
            "[%s]\t%s instr=%d, exit=%s. Input string is %s"
            % (suffix_count, rv, n, c, toc(repr(curr_str), "yellow"))
        )
    elif rv == "wrong":
        overprint(
            "[%s]\t%s instr=%d, exit=%s. Input string is %s"
            % (suffix_count, rv, n, c, toc(repr(curr_str), "red")),
            end="\r",
            flush=True,
        )
    pause()


# Binary-searches for the shortest prefix of suffix that still maximises the coverage
# difference relative to running the program on prefix alone
# accepted collects any complete (exit-0) strings found during the search
# Returns (accepted, best_suffix, best_diff) where best_diff is the largest coverage delta seen
def minimise_suffix(
    prefix: str, suffix: str, log_level: int = 0, suffix_count: str = ""
) -> tuple[list[str], str, int]:
    accepted = []
    best_suffix = suffix

    string_to_try = prefix + suffix

    # establish the baseline coverage for the prefix without any suffix
    _, base_instructions, _ = validate_prog(prefix)
    expanded_rv, expanded_instructions, expanded_c = validate_prog(string_to_try)

    if log_level:
        log_program_result(
            prefix + suffix,
            expanded_rv,
            expanded_instructions,
            expanded_c,
            suffix_count,
        )

    best_diff = abs(expanded_instructions - base_instructions)

    min_length = 0
    max_length = len(suffix)

    # binary search over suffix lengths: shrink toward the shortest suffix that keeps best_diff
    while min_length < max_length:
        expanded_length = min_length + (max_length - min_length) // 2

        if expanded_length == 0:
            break

        curr_str = prefix + suffix[:expanded_length]
        rv, n, c = validate_prog(curr_str)

        diff = abs(n - base_instructions)

        if log_level:
            log_program_result(curr_str, rv, n, c, suffix_count)
            # print(f"diff={diff}")

        # if this shorter suffix still achieves at least best_diff, keep shrinking left
        if diff >= best_diff:
            best_diff = diff
            best_suffix = suffix[:expanded_length]
            max_length = expanded_length
        else:
            min_length = expanded_length + 1

        if rv == "complete":
            accepted.append(curr_str)

        # no coverage change and not a complete parse — suffix adds nothing useful
        if diff == 0 and rv != "complete":
            break

    return suffix, accepted, best_suffix, best_diff


# Picks a character for the first level of suffix generation: first selects one of the seven
# categories uniformly at random, then picks uniformly within that category; this gives equal
# weight to each category regardless of how many characters it contains
def charset_1() -> str:
    return random.choice(random.choice(CHARSET_1_CATEGORIES))


def charset_2() -> str:
    return random.choice(random.choice(CHARSET_2_CATEGORIES))


# Returns a SuffixPopulation of c² individuals: outer loop runs c times (c = SAMPLE_COUNT),
# each iteration drawing a fresh charset_1() character; inner loop of SAMPLE_COUNT iterations
# per outer step; for the first BANK_PERCENTAGE of each inner loop, draws from the suffix bank
# (prepended with that character), falling back to the three-level structure when the bank is
# empty; the remainder of each inner loop always uses the three-level structure:
#   level 1 — charset_1() (category-weighted first character)
#   level 2 — charset_2() (category-weighted second character)
#   level 3 — get_expanded_string (random extension tail)
def generate_suffixes() -> SuffixPopulation:
    individuals = []
    for _ in range(SAMPLE_COUNT):
        char = charset_1()
        curr = []
        for i in range(SAMPLE_COUNT):
            if i < SAMPLE_COUNT * BANK_PERCENTAGE:
                remaining = [s for s in SUFFIXES if s not in curr]
                if remaining:
                    suffix = char + random.choice(remaining)
                else:
                    suffix = char + charset_2() + get_expanded_string()
            else:
                suffix = char + charset_2() + get_expanded_string()
            curr.append(suffix)
            individuals.append(suffix)
    return SuffixPopulation(individuals)


def _init_worker():
    global tmp_JSON
    tmp_JSON = f"/tmp/batman_{os.getpid()}.json"
    os.environ["TMP_JSON"] = tmp_JSON


def _minimise_suffix_worker(args):
    prefix, suffix, log_level, suffix_count = args
    return minimise_suffix(
        prefix, suffix, log_level=log_level, suffix_count=suffix_count
    )


def clearline():
    # print()
    print(" " * 80, end="\r", flush=True)  # clear the \r line


def overprint(s: str, end="\n", flush=False):
    clearline()
    print(s, end=end, flush=flush)


def exec_args(seed_str, new_suffixes, tried_offset, priority, log_level):
    args_list = [
        (
            seed_str,
            suffix,
            log_level,
            "%d| %d/%d %d/%d"
            % (priority, i, SAMPLES_TO_TEST, tried_offset + i, len(POPULATION)),
        )
        for i, suffix in enumerate(new_suffixes)
    ]

    if IS_PARALLEL:
        with ProcessPoolExecutor(initializer=_init_worker) as executor:
            results = list(executor.map(_minimise_suffix_worker, args_list))
    else:
        results = []
        for args in args_list:
            # (suffix, accepted, best_suffix, best_diff)
            result = _minimise_suffix_worker(args)
            results.append(result)
    return results


def evolve_population(results):
    POPULATION.update_fitness(results)
    POPULATION.evolve()


# Expands seed_str by sampling SAMPLES_TO_TEST suffixes from POPULATION, minimising each,
# and collecting complete strings; banks suffixes that achieved the best coverage difference.
# Returns (tried_chars, is_dead_end, extensions, boundary_extensions, n_tried, max_diff):
# the set of first chars sampled, whether no suffix changed coverage and no complete strings
# were found, the list of seed_str+best_suffix[:1] candidates to enqueue, the subset that
# crossed a token boundary, the number of suffix evaluations, and the largest coverage delta.
def generate(
    seed_str: str = "", tried_offset: int = 0, priority: int = 0, log_level=0
) -> tuple[set[str], bool, list[str], set[str], int, int]:
    print()
    print(f"generate: seed prefix {repr(seed_str)}")

    new_suffixes = POPULATION.sample(SAMPLES_TO_TEST)
    tried_chars = {s[0] for s in new_suffixes}

    # Execute our program, and get the results.
    results = exec_args(seed_str, new_suffixes, tried_offset, priority, log_level)

    accepted_list = []
    best_suffixes = []
    for orig_suffix, accepted, best_suffix, best_diff in results:
        best_suffixes.append((best_suffix, best_diff))
        for val in accepted:
            if val not in accepted_list:
                accepted_list.append(val)
            if val not in FOUND:
                FOUND.add(val)
                write("valid_inputs.txt", repr(val) + "\n")

    evolve_population(results)

    max_best_diff = max(best_suffixes, key=lambda x: x[1])[1]
    extensions = []
    boundary_extensions = set()
    if max_best_diff > 0:
        for orig_suffix, accepted, best_suffix, best_diff in results:
            is_boundary = best_diff > 0 and len(best_suffix) < len(orig_suffix)
            if best_diff == max_best_diff:
                SUFFIXES.add(best_suffix)
            if best_diff > 0:
                ext = seed_str + best_suffix[:1]
                extensions.append(ext)
                if is_boundary:
                    boundary_extensions.add(ext)
            if not ADD_PREFIXES_FROM_ACCEPTED:
                continue
            for acc in accepted:
                if not acc:
                    continue
                ext = acc[:-1]
                extensions.append(ext)
                boundary_extensions.add(ext)
    is_dead_end = (max_best_diff == 0 and not accepted_list)
    return (
        tried_chars,
        is_dead_end,
        list(set(extensions)),  # dedup
        boundary_extensions,
        len(best_suffixes),
        max_best_diff,
    )


def write(w, s):
    with open(w, "a") as myfile:
        myfile.write(s)


def touch(w):
    write(w, "")


def dump(jfile, jval):
    with open(jfile, "w") as f:
        json.dump(jval, f, indent=2)


class PrefixEntry:
    def __init__(self, prefix, depth=0, boundary_count=0):
        self.prefix = prefix
        self.priority = 0
        self.remaining = set(CHARSET)
        self.tried_count = 0
        self.generate_count = 0
        self.extension_count = 0
        self.depth = depth
        self.boundary_count = boundary_count


def save_priority_queue(entries):
    by_priority = {}
    by_prefix = {}
    for e in entries:
        by_priority.setdefault(e.priority, []).append(e.prefix)
        by_prefix[e.prefix] = e.priority
    dump(
        "priority_by_priority.json", {str(k): v for k, v in sorted(by_priority.items())}
    )
    dump("priority_by_prefix.json", by_prefix)


# maintains a dict of PrefixEntry objects seeded with single chars (or PREFIX).
# At each iteration picks a random entry from the lowest-priority group.
def create_valid_strings(log_level):
    if PREFIX:
        entries = {PREFIX: PrefixEntry(PREFIX)}
    else:
        entries = {c: PrefixEntry(c) for c in CHARSET}

    while entries:
        # Pick the entry with the minimum priority to explore. Random choice
        # is the tie breaker.
        min_p = min(e.priority for e in entries.values())
        entry = random.choice([e for e in entries.values() if e.priority == min_p])
        write("selected_prefix.txt", repr(entry.prefix) + "\n")
        process_entry(entry, entries, log_level)
        # Priority queue is saved after each entry is explored.
        save_priority_queue(entries.values())

    print("All prefixes exhausted")

# Main driver: calls generate(), updates the entry's priority via the active
# priority function, enqueues any new extensions, and removes entries whose
# remaining first-char set is exhausted.
def process_entry(entry, entries, log_level):
    (
        tried_chars,
        is_dead_end,
        extensions,
        boundary_extensions,
        n_tried,
        max_instructions,
    ) = generate(entry.prefix, entry.tried_count, entry.priority, log_level)
    entry.tried_count += n_tried
    entry.generate_count += 1
    entry.remaining -= tried_chars

    candidates = [
        ext
        for ext in extensions
        if not DISCARD_NON_BOUNDARY_EXTENSIONS or ext in boundary_extensions
    ]
    new_extensions = [ext for ext in candidates if ext not in entries]
    entry.extension_count += len(new_extensions)

    entry.priority = _PRIORITY_FNS[PRIORITY_FUNCTION](
        entry, n_tried, max_instructions
    )

    for ext in new_extensions:
        if ext in boundary_extensions:
            child_bc = entry.boundary_count + 1
        entries[ext] = PrefixEntry(
            ext, depth=entry.depth + 1, boundary_count=child_bc
        )

    if not entry.remaining or is_dead_end:
        del entries[entry.prefix]



if __name__ == "__main__":
    POPULATION = generate_suffixes()
    print("generated", len(POPULATION))
    create_valid_strings(1)
