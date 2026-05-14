#!/usr/bin/env python3
# coding: utf-8
# import pudb
# bp = pudb.set_trace

import json
import os
import random
import subprocess
from collections import defaultdict

# import string
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
    "(",
    ")",
    "<",
    ">",
    "1",
    "0",
    "a",
    "b",
    ":",
    '"',
    ",",
    ".",
]


queue = set([""] + CHARSET)
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
        "sh",
        "bin/handle_coverage.sh",
        my_program,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=5, input=input_string
    )
    instructions = extract_blocks_from_json()
    return instructions, result.returncode


def validate_prog(input_str, log_level):
    try:
        instructions_extended = None
        instructions_current = None

        instructions_current_count = 0
        instructions_current_total = 0
        return_codes = 0
        for _ in range(COUNT):
            instructions_current, returncode_current = get_instructions(input_str)
            if instructions_current is None:
                if log_level:
                    print("Could not parse instruction count")
                continue
            return_codes += returncode_current
            instructions_current_count += 1
            instructions_current_total += instructions_current
        if return_codes == 0:
            if log_level:
                print(("Program returned 0 - complete"))  # , 'green'))
            return "complete", 0, ""

        if instructions_current_count == 0:
            if log_level:
                print("Could not parse instruction count")
            return "wrong", 101, ""
        avg_instructions_current = (
            instructions_current_total * 1.0 / instructions_current_count
        )

        # Get instruction count for extended input (with arbitrary character)
        instructions_extended_total = 0
        instructions_extended_count = 0

        for _ in range(COUNT):
            c = get_next_char(log_level, input_str)
            if c is None:
                continue

            extended_input = input_str + c
            instructions_extended, _returncode_extended = get_instructions(
                extended_input
            )
            if instructions_extended is None:
                continue
            instructions_extended_total += instructions_extended
            instructions_extended_count += 1

        if instructions_extended_total == 0:
            if log_level:
                print("Could not parse instruction count for extended input")
            return "wrong", 102, ""

        avg_instructions_extended = (
            instructions_extended_total * 1.0 / instructions_extended_count
        )

        if abs(avg_instructions_extended - avg_instructions_current) > MIN_INCREASE:
            if log_level:
                print(
                    (
                        f"Instructions increased: {instructions_extended} > {instructions_current} - incomplete"
                    )
                )  # , 'yellow'))
            return "incomplete", -1, ""
        else:
            if log_level:
                print(
                    (
                        f"Instructions did not increase: {instructions_extended} <= {instructions_current} - incorrect"
                    )
                )  # , 'red'))
            return "incorrect", 1, ""

    except subprocess.TimeoutExpired:
        if log_level:
            print("Command timed out")
        return "wrong", -1, ""
    except Exception as e:
        if log_level:
            print(f"Error running command: {e}")
        return "wrong", -1, ""


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


def generate(log_level, seed_str: str = "") -> str | None:
    """
    Feed the seed string with a long addition.
    If it's rejected/
    """
    global queue, used

    prev_str = seed_str
    backtracked = False

    while True:
        # allow one backtracking.
        if len(used[seed_str]) == len(CHARSET):
            del used[seed_str]

            if seed_str in queue:
                queue.remove(seed_str)

            if backtracked:
                return None
            backtracked = True
            prev_str = prev_str[0:-1]

        # generate suffixes
        curr_suffixes = []

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

        for suffix in curr_suffixes:
            curr_str = prev_str + suffix
            rv, n, c = validate_prog(curr_str, log_level)
            if log_level:
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
                elif rv == "incorrect":
                    print(
                        "%s n=%d, c=%s. Input string is %s"
                        % (rv, n, c, toc(repr(curr_str), "red"))
                    )
            if rv == "complete":
                queue.add(curr_str)
                return curr_str
            elif rv == "incomplete":  # go ahead...
                queue.add(curr_str)
                return None
            elif (
                rv == "incorrect"
            ):  # try again with a new random character do not save current character
                if curr_str in queue:
                    queue.remove(curr_str)
                continue
            else:
                print("ERROR: Unknown")
                break
    return None


def create_valid_strings(n, log_level):
    # tic = time.time()

    with open("valid_inputs.txt", "w") as myfile:
        myfile.write("")
        myfile.close()

    while True:
        prev_str = random.choice(list(queue))
        created_string = generate(log_level, prev_str)
        # toc = time.time()
        if created_string is not None:
            with open("valid_inputs.txt", "a") as myfile:
                myfile.write(created_string + "\n")
                myfile.close()


if __name__ == "__main__":
    create_valid_strings(MAX_STRINGS, 1)
