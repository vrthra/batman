#!/usr/bin/env python3
# coding: utf-8

import json
import os
import random
import string
import subprocess

MAX_STRINGS = 10000
COUNT = 1
MIN_INCREASE = 10
LENGTH_INCREASE = 64

BANK_PERCENTAGE = 0.5  # the percentage of suffixes that will be drawn from $suffixes instead of being generated randomly

my_program = os.environ.get("PROGRAM", "./program.out")
tmp_JSON = os.environ.get("TMP_JSON", "/tmp/tmp.json")

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
suffixes = set([])
MY_SUFFIXES = []


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
def extract_blocks_from_json(json_file: str = tmp_JSON) -> int | None:
    data = json.load(open(json_file))

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
        my_program,
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


# Runs the program on input_str and classifies the outcome as "complete" (exit 0) or "wrong"
# (non-zero exit or timeout); returns a 3-tuple of (status, coverage_count, return_code)
# Returns ("wrong", -1, -1) on timeout or any other exception
def validate_prog(input_str, log_level: int = 0) -> tuple[str, int, int]:
    instructions, ret_code = get_instructions(input_str)
    if ret_code == 0:
        return "complete", instructions if instructions else -1, ret_code
    elif ret_code > 0:  # incorrect
        return "wrong", instructions if instructions else -1, ret_code
    else:  # signal
        return "unexpected", -1, ret_code


def get_expanded_string(expand_length: int = LENGTH_INCREASE) -> str:
    return "".join(random.choice(CHARSET) for _ in range(expand_length))


# Prints a color-coded summary line for curr_str based on the program result rv
# "complete" is green (newline), "incomplete" is yellow (newline), "wrong" is red (overwritten via \r)
# space_len blanks are printed first to erase the previous \r line
def log_program_result(curr_str, rv: str, n: int, c: int, suffix_count: str) -> None:
    space_len = len(curr_str) * 2
    if rv == "complete":
        print(" " * space_len, end="\r", flush=True)  # clear the \r line
        print(
            "[%s]\t%s instr=%d, exit=%s. Input string is %s"
            % (suffix_count, rv, n, c, toc(repr(curr_str), "green"))
        )
    elif rv == "unexpected":
        print(" " * space_len, end="\r", flush=True)  # clear the \r line
        print(
            "[%s]\t%s instr=%d, exit=%s. Input string is %s"
            % (suffix_count, rv, n, c, toc(repr(curr_str), "yellow"))
        )
    elif rv == "wrong":
        print(" " * space_len, end="\r", flush=True)  # clear the \r line
        print(
            "[%s]\t%s instr=%d, exit=%s. Input string is %s"  # % (rv, n, c, toc(repr(curr_str), "red"))
            % (suffix_count, rv, n, c, toc(repr(curr_str), "red")),
            end="\r",
            flush=True,
        )


# Binary-searches for the shortest prefix of suffix that still maximises the coverage
# difference relative to running the program on prefix alone
# accepted collects any complete (exit-0) strings found during the search
# Returns (accepted, best_suffix, best_diff) where best_diff is the largest coverage delta seen
def minimise_suffix(
    prefix: str, suffix: str, log_level: int = 0, suffix_count: str = ""
) -> tuple[list[str], str, int]:
    accepted = []
    best_suffix = suffix

    # establish the baseline coverage for the prefix without any suffix
    _, base_instructions, _ = validate_prog(prefix)
    expanded_rv, expanded_instructions, expanded_c = validate_prog(prefix + suffix)

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

    return accepted, best_suffix, best_diff


# Picks a character for the second level of suffix generation: first selects one of the five
# categories uniformly at random, then picks uniformly within that category; this gives equal
# weight to each category regardless of how many characters it contains
def charset_1() -> str:
    return random.choice(random.choice(CHARSET_1_CATEGORIES))


def charset_2() -> str:
    return random.choice(random.choice(CHARSET_2_CATEGORIES))


# Yields c² suffix candidates: outer loop over each char in CHARSET (c iterations), inner loop
# of SAMPLE_COUNT (c) iterations per char; for the first BANK_PERCENTAGE of each inner loop,
# draws from the suffixes bank (prepended with char), falling back to the three-level structure
# when the bank is empty; the remainder of each inner loop always uses the three-level structure:
#   level 1 — charset_1() (category-weighted first character)
#   level 2 — charset_2() (category-weighted second character)
#   level 3 — get_expanded_string (random extension from the two-char prefix)
def generate_suffixes():
    for _ in range(SAMPLE_COUNT):
        char = charset_1()
        # track suffixes chosen from the bank this round to avoid duplicates within the group
        curr_suffixes = []
        for i in range(SAMPLE_COUNT):
            if i < SAMPLE_COUNT * BANK_PERCENTAGE:
                remaining_suffixes = [s for s in suffixes if s not in curr_suffixes]
                if remaining_suffixes:
                    # prepend char to a randomly chosen known-good suffix from the bank
                    suffix = char + random.choice(remaining_suffixes)
                else:
                    # bank empty: use three-level structure as fallback
                    suffix = char + charset_2() + get_expanded_string()
            else:
                # beyond the bank quota: always use the three-level structure
                suffix = char + charset_2() + get_expanded_string()
            curr_suffixes.append(suffix)
            MY_SUFFIXES.append(suffix)
    return MY_SUFFIXES


# Expands seed_str by trying sampled suffixes from MY_SUFFIXES, minimising each, and
# collecting complete strings; banks suffixes that achieved the best coverage difference.
# Returns (tried_chars, is_dead_end, extensions): the set of first-chars of sampled
# suffixes, whether no suffix produced any coverage change, and the list of
# seed_str+suffix strings that achieved the maximum coverage diff (to enqueue as new prefixes).
def generate(
    log_level, seed_str: str = "", tried_offset: int = 0
) -> tuple[set[str], bool, list[str], int]:
    global suffixes

    print(f"seed prefix {repr(seed_str)}")

    best_suffixes = []
    res = []
    tried_chars = set()

    new_suffixes = random.sample(MY_SUFFIXES, SAMPLES_TO_TEST)

    for i, suffix in enumerate(new_suffixes):
        tried_chars.add(suffix[0])
        accepted, best_suffix, best_diff = minimise_suffix(
            seed_str,
            suffix,
            log_level=log_level,
            suffix_count="%d/%d %d/%d" % (i, SAMPLES_TO_TEST, tried_offset + i, len(MY_SUFFIXES)),
        )

        for val in accepted:
            if val not in res:
                res.append(val)
                write("valid_inputs.txt", repr(val) + "\n")

        best_suffixes.append((best_suffix, best_diff))

        if res:
            break

    max_best_diff = max(best_suffixes, key=lambda x: x[1])[1]
    extensions = []
    if max_best_diff > 0:
        for suffix, diff in best_suffixes:
            if diff == max_best_diff:
                suffixes.add(suffix)
                extensions.append(seed_str + suffix)

    return tried_chars, (max_best_diff == 0 and not res), extensions, len(best_suffixes)


def write(w, s):
    with open(w, "a") as myfile:
        myfile.write(s)
        myfile.close()


def touch(w):
    write(w, "")


class PrefixEntry:
    def __init__(self, prefix):
        self.prefix = prefix
        self.priority = len(prefix)  # shorter prefixes have higher priority
        self.remaining = set(CHARSET)
        self.tried_count = 0


# Main driver: maintains a priority queue of prefixes seeded with single chars.
# Always picks from the lowest-priority group at random. Priority = len(prefix),
# so shorter prefixes are always preferred over longer ones. Dead ends increment
# priority by 1 to defer the entry behind peers of the same length. Productive
# continuations are enqueued as new, longer entries. An entry is discarded once
# all possible first-char extensions have been tried.
def save_priority_queue(entries):
    by_priority = {}
    by_prefix = {}
    for e in entries:
        by_priority.setdefault(e.priority, []).append(e.prefix)
        by_prefix[e.prefix] = e.priority
    with open("priority_by_priority.json", "w") as f:
        json.dump({str(k): v for k, v in sorted(by_priority.items())}, f, indent=2)
    with open("priority_by_prefix.json", "w") as f:
        json.dump(by_prefix, f, indent=2)


def create_valid_strings(log_level):
    touch("valid_inputs.txt")
    entries = [PrefixEntry(c) for c in CHARSET]

    while entries:
        min_p = min(e.priority for e in entries)
        entry = random.choice([e for e in entries if e.priority == min_p])

        tried_chars, is_dead_end, extensions, n_tried = generate(
            log_level, entry.prefix, entry.tried_count
        )
        entry.tried_count += n_tried
        entry.remaining -= tried_chars

        entry.priority += 1
        save_priority_queue(entries)

        if extensions:
            for ext in extensions:
                entries.append(PrefixEntry(ext))
            save_priority_queue(entries)

        if not entry.remaining:
            entries.remove(entry)
            save_priority_queue(entries)

    print("All prefixes exhausted")


if __name__ == "__main__":
    MY_SUFFIXES = generate_suffixes()
    print("generated", len(MY_SUFFIXES))
    create_valid_strings(1)
