#!/bin/bash
# Short archival integrity maintenance; not a simulation or research experiment.
set -euo pipefail
test -n "${SLURM_JOB_ID:-}" && test -n "${SLURM_JOB_NODELIST:-}"
test "$#" -gt 0
root=$(pwd -P)
[[ "$root" == /XYFS02/HDD_POOL/sysu_pww/sysu_pww_2/dsh-simulation/inputs/* ]]
export PATH=/usr/bin:/bin
export HOME="$root/tmp/verify-$SLURM_JOB_ID-home"
export TMPDIR="$root/tmp/verify-$SLURM_JOB_ID-tmp"
mkdir -p "$HOME" "$TMPDIR"
for group in "$@"; do
  [[ "$group" =~ ^[a-z]+(-[a-z]+)*$ ]]
  env -u LD_LIBRARY_PATH -u LD_PRELOAD -u PYTHONPATH -u BASH_ENV -u ENV \
    /APP/u22/x86/anaconda3/202309/bin/python3 -I \
    "$root/tools/verify_sealed_archive_hpc.py" --root "$root" --name "$group"
done
