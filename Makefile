I=a
.SUFFIXES:
.SECONDARY:

%.out: src/%.c
	clang -g -o $@ $^ -I include -O0 -fprofile-instr-generate -fcoverage-mapping

%.count: %.out
	@sudo /usr/bin/perf stat -e instructions:u ./$< '$(I)'  2>&1 | grep instructions


clean:
	rm -f *.out *.count

gdbctl.out: src/gdbctl.c
	cc -g -lutil -o $@ $^ -I include

#DBG=-m pudb
DBG=
EXPLORER=bin/batman.py
# EXPLORER=bin/robin.py

pxctl: pxctl.out
	cp $^ $@

run.%: %.out
	env PROGRAM=./$^ python3 $(DBG) $(EXPLORER)

run.cJSON: export PROGRAM=cJSON.out 
run.cJSON: export PREFIX={
run.cJSON: cJSON.out
	python3 $(DBG) $(EXPLORER)

run.calc_parse: export PROGRAM=calc_parse.out 
run.calc_parse: calc_parse.out
	python3 $(DBG) $(EXPLORER)

get:
	wget https://raw.githubusercontent.com/vrthra/mimid/refs/heads/master/Cmimid/examples/vector.h

pull:
	git pull --rebase origin master --autostash

push:
	git push origin master

v:
	vim $(EXPLORER)

reset:
	rm -f priority_by_prefix.json priority_by_priority.json valid_inputs.txt selected_prefix.txt

.PHONY: pull push v reset
