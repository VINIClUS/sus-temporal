#!/bin/bash
# PreToolUse (Bash): bloqueia push forçado, remoção de branch, refspec "+" ou ":" vazio e
# qualquer push que mencione main, mesmo dentro de `uv run`, `bash -c` ou `git -C`.
set -euo pipefail

comando="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')"

if ! grep -Eq 'git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+push' <<<"$comando"; then
  exit 0
fi

argumentos="${comando#*push}"
perigosos='(^|[[:space:]])(--force([^[:space:]]*)?|-f|--delete|-d|--mirror|--all|--tags|--prune)([[:space:]]|$)'
refspec_forcado='(^|[[:space:]])\+[^[:space:]]+'
remocao=':[^[:space:]]*'"'"'?([[:space:]]|$)'
alvo_main='(^|[[:space:]:/])main([[:space:]'"'"'"]|$)'

if grep -Eq -- "$perigosos" <<<"$argumentos" \
  || grep -Eq -- "$refspec_forcado" <<<"$argumentos" \
  || grep -Eq -- "(^|[[:space:]])${remocao}" <<<"$argumentos" \
  || grep -Eq -- "$alvo_main" <<<"$argumentos"; then
  echo "push_bloqueado comando=${comando} motivo=force_delete_ou_main_proibidos" >&2
  exit 2
fi
exit 0
