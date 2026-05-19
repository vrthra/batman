#!/usr/bin/env python3
# coding: utf-8
# import pudb
# bp = pudb.set_trace

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

SAMPLE_COUNT = 10
BANK_PERCENTAGE = 0.5  # the percentage of suffixes that will be drawn from $suffixes instead of being generated randomly

my_program = os.environ.get("PROGRAM", "./program.out")
# CHARSET = (
#     string.printable
# )  # ['[',']','{','}','(',')','<','>','1','0','a','b',':','"',',','.', '\'']
CHARSET = [
    "[",
    "]",
    "{",
    "}",
    "1",
    "0",
    "a",
    "b",
    ":",
    '"',
    ",",
    ".",
]


queue = set([""] + list(CHARSET))
used: dict[str, set[str]] = defaultdict(set)
suffixes = set([])


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


def extract_blocks_from_json(json_file: str = "/tmp/tmp.json") -> int | None:
    data = json.load(open(json_file))

    total = 0
    for f in data["data"][0]["functions"]:
        for b in f.get("regions", []):
            total += b[4]

    return total if total > 0 else None


# Run perf and extract instruction count
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


def log_program_result(curr_str, rv: str, n: int, c: int) -> None:
    if rv == "complete":
        print(
            "%s n=%d, c=%s. Input string is %s"
            % (rv, n, c, toc(repr(curr_str), "green"))
        )
    elif rv == "incomplete":
        print(
            "%s n=%d, c=%s. Input string is %s"
            % (rv, n, c, toc(repr(curr_str), "yellow"))
        )
    elif rv == "wrong":
        print(
            "%s n=%d, c=%s. Input string is %s" % (rv, n, c, toc(repr(curr_str), "red"))
        )


def minimise_suffix(
    prefix: str, suffix: str, log_level: int = 0
) -> tuple[list[str], str, int]:
    """ """
    accepted = []
    best_suffix = suffix

    _, base_instructions, _ = validate_prog(prefix)
    expanded_rv, expanded_instructions, expanded_c = validate_prog(prefix + suffix)

    if log_level:
        log_program_result(
            prefix + suffix, expanded_rv, expanded_instructions, expanded_c
        )

    best_diff = abs(expanded_instructions - base_instructions)

    min_length = 0
    max_length = len(suffix)

    while min_length < max_length:
        expanded_length = min_length + (max_length - min_length) // 2

        if expanded_length == 0:
            break

        curr_str = prefix + suffix[:expanded_length]
        rv, n, c = validate_prog(curr_str)

        diff = abs(n - base_instructions)

        if log_level:
            log_program_result(curr_str, rv, n, c)
            print(f"diff={diff}")

        if diff >= best_diff:
            best_diff = diff
            best_suffix = suffix[:expanded_length]
            max_length = expanded_length
        else:
            min_length = expanded_length + 1

        if rv == "complete":
            accepted.append(curr_str)

        if diff == 0 and rv != "complete":
            break

    return accepted, best_suffix, best_diff


def generate(log_level, seed_str: str = "") -> list[str]:
    """
    Feed the seed string with a long addition.
    """
    global queue, used, suffixes

    prev_str = seed_str

    curr_suffixes = []
    res = []

    for i in range(SAMPLE_COUNT):
        # draw from the bank if we haven't exhausted it yet
        if i < SAMPLE_COUNT * BANK_PERCENTAGE:
            remaining_suffixes = [s for s in suffixes if s not in curr_suffixes]
            if remaining_suffixes:
                curr_suffixes.append(random.choice(remaining_suffixes))
            else:
                curr_suffixes.append(get_expanded_string(""))
        else:
            curr_suffixes.append(get_expanded_string(""))

    best_suffixes = []

    for suffix in curr_suffixes:
        accepted, best_suffix, best_diff = minimise_suffix(
            prev_str, suffix, log_level=log_level
        )
        if accepted:
            res += accepted

        best_suffixes.append((best_suffix, best_diff))

    max_best_diff = max(best_suffixes, key=lambda x: x[1])[1]

    if max_best_diff == 0 and len(res) == 0:
        print("Invalid prefix: %s" % toc(repr(seed_str), "red"))

        to_remove = set()

        for val in queue:
            if val.startswith(seed_str):
                to_remove.add(val)

        queue.difference_update(to_remove)
    elif max_best_diff > 0:
        print("Incomplete: %s" % toc(repr(seed_str), "yellow"))

        for suffix, diff in best_suffixes:
            queue.add(seed_str + suffix)

            if diff == max_best_diff:
                suffixes.add(suffix)

        for val in res:
            queue.add(val)

    return res


def create_valid_strings(n, log_level):

    with open("valid_inputs.txt", "w") as myfile:
        myfile.write("")
        myfile.close()

    while True:
        if len(queue) == 0:
            print("Queue empty, returning")
            return

        prev_str = random.choice(list(queue))
        created_strings = generate(log_level, prev_str)
        for created_string in created_strings:
            with open("valid_inputs.txt", "a") as myfile:
                myfile.write(repr(created_string) + "\n")
                myfile.close()


if __name__ == "__main__":
    create_valid_strings(MAX_STRINGS, 1)
