#!/usr/bin/env bash
# Run only after explicit authorization, as the selected non-root SSH user.
# Arguments: staging-directory OpenFOAM-bashrc blastFoam-bashrc [proxy-url].
set -euo pipefail
if [ "$(id -u)" -eq 0 ]; then echo 'Refusing installation as root.' >&2; exit 1; fi
stage=$(realpath "${1:?staging directory required}")
foam_rc=$(realpath "${2:?OpenFOAM bashrc required}")
blast_rc=$(realpath "${3:?blastFoam bashrc required}")
case "$stage/" in "$HOME/"*) ;; *) echo 'Staging must be inside this user home.' >&2; exit 1;; esac
proxy_url=${4:-}
cd "$stage"
sha256sum -c ripgrep.sha256
mkdir -p "$HOME/.dsh-remote-ssh/cli/bin" "$HOME/.dsh-remote-ssh/bin"
cli_stage=$(mktemp -d "$stage/cli-extract.XXXXXX")
rg_stage=$(mktemp -d "$stage/rg-extract.XXXXXX")
tar -xzf code-cli.tar.gz -C "$cli_stage"
tar -xzf ripgrep-14.1.1-x86_64-unknown-linux-musl.tar.gz -C "$rg_stage"
test -f "$cli_stage/code"
test -f "$rg_stage/ripgrep-14.1.1-x86_64-unknown-linux-musl/rg"
install -m 0755 "$cli_stage/code" "$HOME/.dsh-remote-ssh/cli/bin/code.new"
"$HOME/.dsh-remote-ssh/cli/bin/code.new" --version
"$HOME/.dsh-remote-ssh/cli/bin/code.new" agent host --help >/dev/null
mv "$HOME/.dsh-remote-ssh/cli/bin/code.new" "$HOME/.dsh-remote-ssh/cli/bin/code"
install -m 0755 "$rg_stage/ripgrep-14.1.1-x86_64-unknown-linux-musl/rg" "$HOME/.dsh-remote-ssh/bin/rg"
# Set the environment only for the private Agent Host process and its children.
# No changes to shell startup files or system PATH.
{
  printf '#!/usr/bin/env bash\n'
  if [ -n "$proxy_url" ]; then
    printf 'export http_proxy=%q https_proxy=%q HTTP_PROXY=%q HTTPS_PROXY=%q NO_PROXY=127.0.0.1,localhost\n' "$proxy_url" "$proxy_url" "$proxy_url" "$proxy_url"
  fi
  printf 'export PATH="$HOME/.dsh-remote-ssh/bin:$PATH"\n'
  printf 'source %q\n' "$foam_rc"
  printf 'source %q\n' "$blast_rc"
  printf 'exec "$HOME/.dsh-remote-ssh/cli/bin/code" "$@"\n'
} > "$HOME/.dsh-remote-ssh/bin/code-with-env"
chmod 0755 "$HOME/.dsh-remote-ssh/bin/code-with-env"
"$HOME/.dsh-remote-ssh/bin/rg" --version
