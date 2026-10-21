#!/usr/bin/env bash
set -eo pipefail
case_dir=$1
for env_name in OPENFOAM_BASHRC BLASTFOAM_BASHRC; do
  env_path=${!env_name:-}
  if [[ -n "$env_path" ]]; then
    [[ -r "$env_path" ]] || { echo "$env_name is not readable" >&2; exit 2; }
    if [[ "$env_name" == BLASTFOAM_BASHRC ]]; then
      MAKE=True source "$env_path"
    else
      source "$env_path"
    fi
  fi
done
command -v blastFoam >/dev/null || { echo 'blastFoam is unavailable after environment setup' >&2; exit 2; }
cd -- "$case_dir"
# Windows transfers do not preserve executable bits. Change copied scripts only.
while IFS= read -r -d '' script; do
  sed -i 's/\r$//' "$script"
  chmod u+x "$script"
done < <(find . -type f \( -name Allrun -o -name Allclean -o -name '*.sh' \) -print0)
exec bash ./Allrun
