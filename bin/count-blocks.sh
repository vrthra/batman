#!/bin/sh

bin="$1"
shift
TMP_BASE="${TMP_JSON%.json}"
TMP_BASE="${TMP_BASE:-/tmp/tmp}"
rm -f ${TMP_BASE}.profraw ${TMP_BASE}.profdata

LLVM_PROFILE_FILE=${TMP_BASE}.profraw "./$bin" "${@}" >/dev/null
RET_CODE=$?

if [ "$(uname)" = "Linux" ]; then
  llvm-profdata-18 merge ${TMP_BASE}.profraw -o ${TMP_BASE}.profdata
else
  xcrun llvm-profdata merge ${TMP_BASE}.profraw -o ${TMP_BASE}.profdata
fi

if [ "$(uname)" = "Linux" ]; then
  llvm-cov-18 export "$bin" \
      -instr-profile=${TMP_BASE}.profdata \
      --format=text > ${TMP_BASE}.json
else
  xcrun llvm-cov export "$bin" \
      -instr-profile=${TMP_BASE}.profdata \
      --format=text > ${TMP_BASE}.json
fi

exit $RET_CODE
