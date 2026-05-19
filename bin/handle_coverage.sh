#!/bin/sh

bin="$1"
shift
rm -f /tmp/tmp.profraw /tmp/tmp.profdata

LLVM_PROFILE_FILE=/tmp/tmp.profraw "./$bin" "${@}" >/dev/null
RET_CODE=$?

llvm-profdata merge /tmp/tmp.profraw -o /tmp/tmp.profdata

llvm-cov export "$bin" \
    -instr-profile=/tmp/tmp.profdata \
    --format=text > /tmp/tmp.json

exit $RET_CODE
