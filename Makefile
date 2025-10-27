count:
	@sudo perf stat -e instructions:u ./cgidecode a         2>&1 | grep instructions
	@sudo perf stat -e instructions:u ./cgidecode aa        2>&1 | grep instructions
	@sudo perf stat -e instructions:u ./cgidecode aaa       2>&1 | grep instructions

%.out: src/%.c
	cc -o $@ $^ -I src

%.count: %.out
	@sudo perf stat -e instructions:u ./$< a         2>&1 | grep instructions > $@


wget https://raw.githubusercontent.com/vrthra/mimid/refs/heads/master/Cmimid/examples/vector.h
