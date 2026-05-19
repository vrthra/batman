#!/bin/sh

bin="$1"
shift
rm -f /tmp/tmp.profraw /tmp/tmp.profdata

LLVM_PROFILE_FILE=/tmp/tmp.profraw "./$bin" "${@}" >/dev/null
RET_CODE=$?

if [ "$(uname)" = "Linux" ]; then
  llvm-profdata-18 merge /tmp/tmp.profraw -o /tmp/tmp.profdata
else
  xcrun llvm-profdata merge /tmp/tmp.profraw -o /tmp/tmp.profdata
fi

if [ "$(uname)" = "Linux" ]; then
  llvm-cov-18 export "$bin" \
      -instr-profile=/tmp/tmp.profdata \
      --format=text > /tmp/tmp.json
else
  xcrun llvm-cov export "$bin" \
      -instr-profile=/tmp/tmp.profdata \
      --format=text > /tmp/tmp.json
fi

exit $RET_CODE
