#!/usr/bin/env python3
# coding: utf-8

import json
import os
import random

# import string
import subprocess
from collections import defaultdict

# import time

MAX_STRINGS = 10000
COUNT = 1
MIN_INCREASE = 10
LENGTH_INCREASE = 64

BANK_PERCENTAGE = 0.5  # the percentage of suffixes that will be drawn from $suffixes instead of being generated randomly

my_program = os.environ.get("PROGRAM", "./program.out")
tmp_JSON = os.environ.get('TMP_JSON', "/tmp/tmp.json")

# CHARSET = (
#     string.printable
# )  # ['[',']','{','}','(',')','<','>','1','0','a','b',':','"',',','.', '\'']
CHARSET = [
    "[", "]",
    "{", "}",
    "1", "0",
    "a", "b",
    ":", '"', ",", ".",
]
SAMPLE_COUNT = len(CHARSET)

# queue holds prefixes to explore; initialised with the empty string and all single characters
queue = set([""] + list(CHARSET))
# used tracks which characters have already been tried after each prefix, to avoid redundant runs
used: dict[str, set[str]] = defaultdict(set)
# suffixes is the bank of suffix strings found to cause large coverage differences
suffixes = set([])


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
def extract_blocks_from_json(json_file: str = tmp_JSON ) -> int | None:
    data = json.load(open(json_file))

    total = 0
    for f in data["data"][0]["functions"]:
        for b in f.get("regions", []):
            total += b[4]

    return total if total > 0 else None


# Run perf and extract instruction count
# Runs the target program under handle_coverage.sh with input_string fed via stdin,
# then reads the coverage count from the JSON report written by that script
def get_instructions(input_string):
    cmd = [
        "bash",
        "bin/handle_coverage.sh",
        my_program,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=5, input=input_string
    )
    instructions = extract_blocks_from_json()
    return instructions, result.returncode


# Runs the program on input_str and classifies the outcome as "complete" (exit 0) or "wrong"
# (non-zero exit or timeout); returns a 3-tuple of (status, coverage_count, return_code)
# Returns ("wrong", -1, -1) on timeout or any other exception
def validate_prog(input_str, log_level: int = 0) -> tuple[str, int, int]:
    try:
        instructions, ret_code = get_instructions(input_str)

        if instructions is None:
            raise Exception(f"Could not parse instruction count for {repr(input_str)}")

        if ret_code == 0:
            if log_level:
                print(("Program returned 0 - complete"))  # , 'green'))
            return "complete", instructions, ret_code

        # if log_level:
        #     print(f"Program returned {ret_code}")
        return "wrong", instructions, ret_code
    except subprocess.TimeoutExpired:
        if log_level:
            print("Command timed out")
        return "wrong", -1, -1
    except Exception as e:
        if log_level:
            print(f"Error running command: {e}")
        return "wrong", -1, -1


# Picks a random character from CHARSET that has not yet been tried after prefix
# When check_used is False, the full CHARSET is considered (used during random expansion)
# Records the chosen character in used[prefix] and returns it; returns None if all chars exhausted
def get_next_char(
    prefix: str, log_level: int = 0, check_used: bool = True
) -> str | None:
    global used
    my_charset = [c for c in CHARSET if c not in used[prefix]]

    if not check_used:
        my_charset = CHARSET

    if len(my_charset) == 0:
        return None

    idx = random.randrange(0, len(my_charset), 1)
    input_char = my_charset[idx]
    used[prefix].add(input_char)
    # if (log_level):
    # print(input_char)
    return input_char


# Grows prefix by appending up to expand_length randomly chosen characters from CHARSET,
# ignoring the used-character tracking so any character may appear at any position
# Returns as soon as get_next_char returns None (which should not happen with check_used=False)
def get_expanded_string(
    prefix: str, expand_length: int = LENGTH_INCREASE, log_level: int = 0
) -> str:
    if log_level:
        print(f"Expanding string: {prefix}")

    res = prefix

    for _ in range(expand_length):
        input_char = get_next_char(res, log_level, check_used=False)
        if input_char is None:
            return res
        res += input_char

    return res


# Prints a color-coded summary line for curr_str based on the program result rv
# "complete" is green (newline), "incomplete" is yellow (newline), "wrong" is red (overwritten via \r)
# space_len blanks are printed first to erase the previous \r line
def log_program_result(curr_str, rv: str, n: int, c: int) -> None:
    space_len = len(curr_str) * 2
    if rv == "complete":
        print(" " * space_len, end="\r", flush=True)  # clear the \r line
        print(
            "%s n=%d, c=%s. Input string is %s"
            % (rv, n, c, toc(repr(curr_str), "green"))
        )
    elif rv == "incomplete":
        print(" " * space_len, end="\r", flush=True)  # clear the \r line
        print(
            "%s n=%d, c=%s. Input string is %s"
            % (rv, n, c, toc(repr(curr_str), "yellow"))
        )
    elif rv == "wrong":
        print(" " * space_len, end="\r", flush=True)  # clear the \r line
        print(
            "%s n=%d, c=%s. Input string is %s"  # % (rv, n, c, toc(repr(curr_str), "red"))
            % (rv, n, c, toc(repr(curr_str), "red")),
            end="\r",
            flush=True,
        )


# Binary-searches for the shortest prefix of suffix that still maximises the coverage
# difference relative to running the program on prefix alone
# accepted collects any complete (exit-0) strings found during the search
# Returns (accepted, best_suffix, best_diff) where best_diff is the largest coverage delta seen
def minimise_suffix(
    prefix: str, suffix: str, log_level: int = 0
) -> tuple[list[str], str, int]:
    accepted = []
    best_suffix = suffix

    # establish the baseline coverage for the prefix without any suffix
    _, base_instructions, _ = validate_prog(prefix)
    expanded_rv, expanded_instructions, expanded_c = validate_prog(prefix + suffix)

    if log_level:
        log_program_result(
            prefix + suffix, expanded_rv, expanded_instructions, expanded_c
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
            log_program_result(curr_str, rv, n, c)
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


# Yields c² suffix candidates: outer loop over each char in CHARSET (c iterations), inner loop
# of SAMPLE_COUNT (c) iterations per char; for the first BANK_PERCENTAGE of each inner loop,
# draws from the suffixes bank (prepended with char), falling back to random expansion when the
# bank is empty; the remainder of each inner loop always uses random expansion
def generate_suffixes():
    for char in CHARSET:
        # track suffixes chosen from the bank this round to avoid duplicates within the group
        curr_suffixes = []
        for i in range(SAMPLE_COUNT):
            if i < SAMPLE_COUNT * BANK_PERCENTAGE:
                remaining_suffixes = [s for s in suffixes if s not in curr_suffixes]
                if remaining_suffixes:
                    # prepend char to a randomly chosen known-good suffix from the bank
                    suffix = char + random.choice(remaining_suffixes)
                else:
                    # bank is empty; fall back to random expansion starting from char
                    suffix = get_expanded_string(char)
            else:
                # beyond the bank quota: always generate a fresh random suffix
                suffix = get_expanded_string(char)
            curr_suffixes.append(suffix)
            yield suffix


# Expands seed_str by trying all suffixes from generate_suffixes(), minimising each, and
# collecting complete strings; updates queue and suffixes based on whether the prefix was
# productive, a dead end, or incomplete
def generate(log_level, seed_str: str = "") -> list[str]:
    global queue, used, suffixes

    print(f"prefix {repr(seed_str)}")

    prev_str = seed_str

    best_suffixes = []
    res = []

    for suffix in generate_suffixes():
        accepted, best_suffix, best_diff = minimise_suffix(
                prev_str, suffix, log_level=log_level
            )

        for val in accepted:
            if val not in res:
                res.append(val)

        best_suffixes.append((best_suffix, best_diff))

    max_best_diff = max(best_suffixes, key=lambda x: x[1])[1]

    # no suffix caused any coverage change and no complete strings found — prefix is a dead end
    if max_best_diff == 0 and len(res) == 0:
        print()
        print("Invalid prefix: %s" % toc(repr(seed_str), "red"))

        # remove the dead-end prefix and all strings that extend it from the queue
        to_remove = set()

        for val in queue:
            if val.startswith(seed_str):
                to_remove.add(val)

        queue.difference_update(to_remove)
    elif max_best_diff > 0:
        print()
        print("Incomplete: %s" % toc(repr(seed_str), "yellow"))

        # enqueue every prefix+suffix candidate for further exploration
        for suffix, diff in best_suffixes:
            queue.add(seed_str + suffix)

            # bank the suffix if it achieved the maximum observed coverage difference
            if diff == max_best_diff:
                suffixes.add(suffix)

        for val in res:
            queue.add(val)

    return res


def write(w, s):
    with open(w, "a") as myfile:
        myfile.write(s)
        myfile.close()

def touch(w): write(w, '')

# Main driver: repeatedly picks a random prefix from the queue, expands it via generate(),
# and appends any newly found complete strings to valid_inputs.txt; stops when the queue empties
def create_valid_strings(n, log_level):
    touch("valid_inputs.txt")

    while True:
        if len(queue) == 0:
            print("Queue empty, returning")
            return

        prev_str = random.choice(list(queue))
        created_strings = generate(log_level, prev_str)
        for created_string in created_strings:
            write("valid_inputs.txt", repr(created_string) + "\n")

if __name__ == "__main__":
    create_valid_strings(MAX_STRINGS, 1)
