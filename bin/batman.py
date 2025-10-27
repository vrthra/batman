#!/usr/bin/env python3
# coding: utf-8
# import pudb
# bp = pudb.set_trace

import os
import subprocess
MAX_STRINGS = 10000
COUNT=10
MIN_INCREASE = 10
my_program = os.environ.get('PROGRAM', './program.out')
#CHARSET = string.printable # ['[',']','{','}','(',')','<','>','1','0','a','b',':','"',',','.', '\'']
CHARSET = ['[',']','{','}','(',')','<','>','1','0','a','b',':','"',',','.', '\'']

def printc(text, color):
    color_codes = {
        "black": "\033[30m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "white": "\033[37m",
        "reset": "\033[0m"  # Resets the color to default
    }

    if color.lower() in color_codes:
        print(f"{color_codes[color.lower()]}{text}{color_codes['reset']}")
    else:
        print(text)

# Run perf and extract instruction count
def get_instructions(input_string):
    cmd = ['./pxctl', my_program , input_string]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    for line in result.stderr.split('\n'):
        if not 'instructions:' in line: continue
        parts = line.strip().split(':')
        if not parts: continue
        try:
            return int(parts[1].replace(',', '')), result.returncode
        except ValueError:
            return None, result.returncode
    return None, result.returncode

def validate_prog(input_str, log_level):
    try:
        instructions_current_count = 0
        instructions_current_total = 0
        return_codes = 0
        for i in range(COUNT):
            instructions_current, returncode_current = get_instructions(input_str)
            if instructions_current is None:
                if log_level: print("Could not parse instruction count")
                continue
            return_codes += returncode_current
            instructions_current_count += 1
            instructions_current_total += instructions_current
        if return_codes == 0:
            if log_level: printc(f"Program returned 0 - complete", 'green')
            return "complete", 0, ""

        if instructions_current_count == 0:
            if log_level: print("Could not parse instruction count")
            return "wrong", 101, ""
        avg_instructions_current = instructions_current_total * 1.0 / instructions_current_count

        # Get instruction count for extended input (with arbitrary character)
        instructions_extended_total = 0
        instructions_extended_count = 0
        used = []
        for i in range(COUNT):
            c = get_next_char(log_level, used)
            extended_input = input_str + c
            instructions_extended, returncode_extended = get_instructions(extended_input)
            if instructions_extended is None: continue
            instructions_extended_total += instructions_extended
            instructions_extended_count += 1

        if instructions_extended_total == 0:
            if log_level: print("Could not parse instruction count for extended input")
            return "wrong", 102, ""

        avg_instructions_extended = instructions_extended_total * 1.0 / instructions_extended_count

        if (avg_instructions_extended - avg_instructions_current) > MIN_INCREASE:
            if log_level:
                printc(f"Instructions increased: {instructions_extended} > {instructions_current} - incomplete", 'yellow')
            return "incomplete", -1, ""
        else:
            if log_level:
                printc(f"Instructions did not increase: {instructions_extended} <= {instructions_current} - incorrect", 'red')
            return "incorrect", 1, ""

    except subprocess.TimeoutExpired:
        if log_level:
            print("Command timed out")
        return "wrong", -1, ""
    except Exception as e:
        if log_level:
            print(f"Error running command: {e}")
        return "wrong", -1, ""

import string
import random

def get_next_char(log_level, used):
    my_charset = [c for c in CHARSET if c not in used]
    idx = random.randrange (0,len(my_charset),1)
    input_char = my_charset[idx]
    used.append(input_char)
    #if (log_level):
        #print(input_char)
    return input_char

def generate(log_level):
    """
    Feed it one character at a time, and see if the parser rejects it.
    If it does not, then append one more character and continue.
    If it rejects, replace with another character in the set.
    :returns completed string
    """
    prev_str = ""
    used = []
    while True:
        # allow one backtracking.
        if len(used) == len(CHARSET):
            prev_str = prev_str[0:-1]
            used = []
        char = get_next_char(log_level, used)
        curr_str = prev_str + str(char)
        rv, n, c = validate_prog(curr_str, log_level)
        if log_level:
            print("%s n=%d, c=%s. Input string is %s" % (rv,n,c, repr(curr_str)))
        if rv == "complete":
            return curr_str
        elif rv == "incomplete": # go ahead...
            used = []
            prev_str = curr_str
            continue
        elif rv == "incorrect": # try again with a new random character do not save current character
            continue
        else:
            print("ERROR What is this I dont know !!!")
            break
    return None
import time
def create_valid_strings(n, log_level):
    tic = time.time()
    while True:
        created_string = generate(log_level)
        toc = time.time()
        if created_string is not None:
            with open("valid_inputs.txt", "a") as myfile:
                var = f"Time used until input was generated: {toc - tic:f}\n" + repr(created_string) + "\n\n" 
                myfile.write(var)
                myfile.close()
if __name__ == '__main__':
    create_valid_strings(MAX_STRINGS, 1)

