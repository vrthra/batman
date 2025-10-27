#!/usr/bin/env python3
# coding: utf-8
# import pudb
# bp = pudb.set_trace

import os
import subprocess
COUNT=10
my_program = os.environ.get('PROGRAM', './program.out')
# Run perf and extract instruction count
def get_instructions(input_string):
    cmd = ['sudo', '/usr/bin/perf', 'stat', '-e', 'instructions:u', my_program , input_string]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    for line in result.stderr.split('\n'):
        if not 'instructions:u' in line: continue
        parts = line.strip().split()
        if not parts: continue
        try:
            return int(parts[0].replace(',', '')), result.returncode
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
            if log_level: print(f"Program returned 0 - complete")
            return "complete", 0, ""

        if instructions_current_count == 0:
            if log_level: print("Could not parse instruction count")
            return "wrong", 101, ""
        avg_instructions_current = instructions_current_total * 1.0 / instructions_current_count

        # Get instruction count for extended input (with arbitrary character)
        instructions_extended_total = 0
        instructions_extended_count = 0
        for i in range(COUNT):
            c = get_next_char(log_level)
            extended_input = input_str + c
            instructions_extended, returncode_extended = get_instructions(extended_input)
            if instructions_extended is None: continue
            instructions_extended_total += instructions_extended
            instructions_extended_count += 1

        if instructions_extended_total == 0:
            if log_level: print("Could not parse instruction count for extended input")
            return "wrong", 102, ""

        avg_instructions_extended = instructions_extended_total * 1.0 / instructions_extended_count

        if (avg_instructions_extended - avg_instructions_current) > 10:
            if log_level:
                print(f"Instructions increased: {instructions_extended} > {instructions_current} - incomplete")
            return "incomplete", -1, ""
        else:
            if log_level:
                print(f"Instructions did not increase: {instructions_extended} <= {instructions_current} - incorrect")
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

def get_next_char(log_level):
    set_of_chars = string.printable # ['[',']','{','}','(',')','<','>','1','0','a','b',':','"',',','.', '\'']
    idx = random.randrange (0,len(set_of_chars),1)
    input_char = set_of_chars[idx]
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
    while True:
        char = get_next_char(log_level)
        curr_str = prev_str + str(char)
        rv, n, c = validate_prog(curr_str, log_level)
        if log_level:
            print("%s n=%d, c=%s. Input string is %s" % (rv,n,c, repr(curr_str)))
        if rv == "complete":
            return curr_str
        elif rv == "incomplete": # go ahead...
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
create_valid_strings(1000000000, 1)
