I=a
.SUFFIXES:
.SECONDARY:

%.out: src/%.c
	cc -g -o $@ $^ -I src

%.count: %.out
	@sudo /usr/bin/perf stat -e instructions:u ./$< '$(I)'  2>&1 | grep instructions


get:
	wget https://raw.githubusercontent.com/vrthra/mimid/refs/heads/master/Cmimid/examples/vector.h

clean:
	rm -f *.out *.count

gdbctl.out: src/gdbctl.c
	cc -g -lutil -o $@ $^ -I src

#DBG=-m pudb
DBG=

pxctl: pxctl.out
	cp $^ $@

run.%: %.out
	env PROGRAM=./$^ python3 $(DBG) bin/batman.py



run.cJSON: cJSON.out
	env PROGRAM=./cJSON.out python3 $(DBG) bin/batman.py

run.calc_parse: calc_parse.out
	env PROGRAM=./calc_parse.out python3 $(DBG) bin/batman.py
