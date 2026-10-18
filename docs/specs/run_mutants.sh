#!/usr/bin/env bash
# Aplica cada mutants/*.patch a una copia del modelo, corre TLC y compara con lo esperado.
#
#   TLA2TOOLS_JAR=/ruta/tla2tools.jar docs/specs/run_mutants.sh [spec_dir] [patrón]
#
# Cada patch lleva una o más líneas "# espera: <each|liveness> NOMBRE=OK|VIOLADA ...".
# Un patch sin hunks (solo cabecera) comprueba el modelo tal cual. Sale con 1 si algún
# resultado no coincide.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
spec_dir="$(cd "${1:-$here/approvals-l3}" && pwd)"
pattern="${2:-*}"
out="${TLC_OUT:-$(mktemp -d -t mutants-XXXXXX)}"
mkdir -p "$out"
mismatches=0

shopt -s nullglob
for patch_file in "$spec_dir"/mutants/$pattern.patch; do
  name="$(basename "$patch_file" .patch)"
  copy="$(mktemp -d -t mutant-XXXXXX)"
  cp "$spec_dir"/*.tla "$spec_dir"/*.cfg "$copy"/
  if grep -q '^--- ' "$patch_file"; then
    patch -s -p1 -d "$copy" <"$patch_file"
  fi
  echo "== $name: $(sed -n '1s/^# //p' "$patch_file")"
  while read -r mode expectations; do
    declare -A want=()
    for pair in $expectations; do want["${pair%%=*}"]="${pair#*=}"; done
    only="$(IFS=,; echo "${!want[*]}")"
    table="$(ONLY="$only" TLC_OUT="$out/$name-$mode" "$here/run_tlc.sh" "$mode" "$copy")"
    for check in "${!want[@]}"; do
      got="$(awk -v n="$check" '$1==n {print $2}' <<<"$table")"
      if [[ "$got" == "${want[$check]}" ]]; then
        printf '   ok     %-8s %-24s %s\n' "$mode" "$check" "$got"
      else
        printf '   FALLA  %-8s %-24s esperaba %s, salió %s\n' "$mode" "$check" "${want[$check]}" "${got:-nada}"
        mismatches=$((mismatches + 1))
      fi
    done
    unset want
  done < <(sed -n 's/^# espera: //p' "$patch_file")
  rm -rf "$copy"
done

echo
echo "Logs en $out"
if [[ "$mismatches" -gt 0 ]]; then
  echo "$mismatches resultado(s) distintos de lo esperado"
  exit 1
fi
echo "Todo coincide con lo esperado"
