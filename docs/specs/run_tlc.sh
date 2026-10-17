#!/usr/bin/env bash
# Corre SANY y TLC sobre una especificación de docs/specs.
#
#   TLA2TOOLS_JAR=/ruta/tla2tools.jar docs/specs/run_tlc.sh <modo> [spec_dir]
#
# Modos:
#   parse     solo SANY (sintaxis y niveles)
#   safety    TLC con <Modulo>.cfg (todas las invariantes; para en la primera violación)
#   each      un TLC por invariante de <Modulo>.cfg y una tabla final
#   liveness  TLC con <Modulo>Liveness.cfg
#
# spec_dir por defecto: docs/specs/approvals-l3. El módulo es el único .tla del directorio.
# Las trazas y los logs quedan en $TLC_OUT (por defecto un directorio temporal); el repo
# no se toca porque TLC corre sobre una copia.
set -euo pipefail

mode="${1:-}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
spec_dir="$(cd "${2:-$here/approvals-l3}" && pwd)"

if [[ -z "${TLA2TOOLS_JAR:-}" || ! -f "${TLA2TOOLS_JAR}" ]]; then
  cat >&2 <<'EOF'
Falta tla2tools.jar (SANY + TLC). No viene en el repo ni se descarga solo.
Bájalo de la release estable oficial:
  https://github.com/tlaplus/tlaplus/releases  (asset "tla2tools.jar")
y apúntalo con:
  export TLA2TOOLS_JAR=/ruta/a/tla2tools.jar
Necesita Java 11 o superior.
EOF
  exit 2
fi

shopt -s nullglob
modules=("$spec_dir"/*.tla)
if [[ ${#modules[@]} -ne 1 ]]; then
  echo "Se esperaba un solo .tla en $spec_dir y hay ${#modules[@]}" >&2
  exit 2
fi
module="$(basename "${modules[0]}" .tla)"

out="${TLC_OUT:-$(mktemp -d -t tlc-XXXXXX)}"
mkdir -p "$out"
work="$(mktemp -d -t tlc-work-XXXXXX)"
trap 'rm -rf "$work"' EXIT
cp "$spec_dir"/*.tla "$spec_dir"/*.cfg "$work"/

java_cmd=(java -XX:+UseParallelGC -Xss16m -cp "$TLA2TOOLS_JAR")

run_tlc() {
  local cfg="$1" log="$2"
  local status=0
  (cd "$work" && "${java_cmd[@]}" tlc2.TLC -workers auto -cleanup \
      -metadir "$work/states-$(basename "$log" .log)" \
      -config "$cfg" "$module.tla") >"$log" 2>&1 || status=$?
  echo "$status"
}

verdict() {
  local log="$1"
  if grep -q "No error has been found" "$log"; then
    echo "OK"
  elif grep -qE "Invariant .* is violated|Temporal properties were violated|Deadlock reached" "$log"; then
    echo "VIOLADA"
  else
    echo "ERROR (ver log)"
  fi
}

case "$mode" in
  parse)
    (cd "$work" && "${java_cmd[@]}" tla2sany.SANY "$module.tla")
    ;;
  safety | liveness)
    cfg="$module.cfg"
    [[ "$mode" == liveness ]] && cfg="${module}Liveness.cfg"
    log="$out/$mode.log"
    status="$(run_tlc "$cfg" "$log")"
    cat "$log"
    echo
    echo "TLC salió con $status: $(verdict "$log"). Log en $log"
    ;;
  each)
    base="$work/$module.cfg"
    mapfile -t invariants < <(awk '/^INVARIANTS/{on=1; next} on && NF {print $1}' "$base")
    header="$(awk '/^INVARIANTS/{exit} {print}' "$base")"
    printf '%-26s %-16s %s\n' "invariante" "resultado" "estados distintos"
    for inv in "${invariants[@]}"; do
      [[ "$inv" == TypeOK ]] && continue
      cfg="$work/only-$inv.cfg"
      printf '%s\nINVARIANTS\n    TypeOK\n    %s\n' "$header" "$inv" >"$cfg"
      log="$out/$inv.log"
      run_tlc "$(basename "$cfg")" "$log" >/dev/null
      distinct="$(grep -oE '[0-9,]+ distinct states found' "$log" | tail -1 | cut -d' ' -f1)"
      printf '%-26s %-16s %s\n' "$inv" "$(verdict "$log")" "${distinct:-?}"
    done
    echo
    echo "Logs y trazas en $out"
    ;;
  *)
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
