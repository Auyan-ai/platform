#!/usr/bin/env bash
# Corre SANY y TLC sobre una especificación de docs/specs.
#
#   TLA2TOOLS_JAR=/ruta/tla2tools.jar docs/specs/run_tlc.sh <modo> [spec_dir]
#
# Modos:
#   parse     solo SANY (sintaxis y niveles)
#   full      TLC solo con TypeOK: tamaño del espacio de estados completo
#   safety    TLC con <Modulo>.cfg (todas las invariantes; para en la primera violación)
#   each      un TLC por invariante de <Modulo>.cfg y una tabla final
#   liveness  un TLC por propiedad de <Modulo>Liveness.cfg y una tabla final
#   trace     run_tlc.sh trace <spec_dir> <Invariante>: traza mínima (1 worker) y resumida.
#             OVERRIDE="MaxFaults=0 Skills={\"refund\"}" cambia constantes; HIDE oculta variables.
#
# ONLY=A,B limita each y liveness a esos nombres.
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
Probado con la release estable v1.7.4 (2.274.532 bytes):
  https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar
  sha256 936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88
Guárdalo fuera del repo (p. ej. ~/.cache/tlaplus/v1.7.4/), compruébalo con sha256sum
y apúntalo con:
  export TLA2TOOLS_JAR=~/.cache/tlaplus/v1.7.4/tla2tools.jar
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

# Una corrida de TLC por nombre de la sección (INVARIANTS o PROPERTIES) de un .cfg.
one_by_one() {
  local base="$work/$1" section="$2" label="$3"
  local names header name cfg log distinct
  mapfile -t names < <(awk -v s="$section" '$1==s{on=1; next} on && NF {print $1}' "$base")
  header="$(awk -v s="$section" '$1==s{exit} {print}' "$base")"
  printf '%-26s %-16s %s\n' "$label" "resultado" "estados distintos"
  for name in "${names[@]}"; do
    [[ "$name" == TypeOK ]] && continue
    [[ -n "${ONLY:-}" && ",$ONLY," != *",$name,"* ]] && continue
    cfg="$work/only-$name.cfg"
    if [[ "$section" == INVARIANTS ]]; then
      printf '%s\nINVARIANTS\n    TypeOK\n    %s\n' "$header" "$name" >"$cfg"
    else
      printf '%s\nPROPERTIES\n    %s\n' "$header" "$name" >"$cfg"
    fi
    log="$out/$name.log"
    run_tlc "$(basename "$cfg")" "$log" >/dev/null
    distinct="$(grep -oE '[0-9,]+ distinct states found' "$log" | tail -1 | cut -d' ' -f1 || true)"
    printf '%-26s %-16s %s\n' "$name" "$(verdict "$log")" "${distinct:-?}"
  done
  echo
  echo "Logs y trazas en $out (resumen legible: docs/specs/tlc_trace.py <log>)"
}

case "$mode" in
  parse)
    (cd "$work" && "${java_cmd[@]}" tla2sany.SANY "$module.tla")
    ;;
  full)
    header="$(awk '$1=="INVARIANTS"{exit} {print}' "$work/$module.cfg")"
    printf '%s\nINVARIANTS\n    TypeOK\n' "$header" >"$work/full.cfg"
    log="$out/full.log"
    status="$(run_tlc full.cfg "$log")"
    grep -E "states generated|depth of the complete|No error|violated" "$log"
    echo "TLC salió con $status: $(verdict "$log"). Log en $log"
    ;;
  trace)
    name="${3:?falta el nombre de la invariante}"
    header="$(awk '$1=="INVARIANTS"{exit} {print}' "$work/$module.cfg")"
    printf '%s\nINVARIANTS\n    TypeOK\n    %s\n' "$header" "$name" >"$work/trace.cfg"
    for kv in ${OVERRIDE:-}; do
      sed -i "s/^\( *${kv%%=*} = \).*/\1${kv#*=}/" "$work/trace.cfg"
    done
    log="$out/trace-$name.log"
    (cd "$work" && "${java_cmd[@]}" tlc2.TLC -workers 1 -cleanup -metadir "$work/states-trace" \
        -config trace.cfg "$module.tla") >"$log" 2>&1 || true
    python3 "$here/tlc_trace.py" "$log" --hide "${HIDE:-lease,hClicks,arrived,unclaimed,tAppr,faults,tKind,attempt,hAtt,rAppr,rAtt,rRes,unknownOut}"
    ;;
  safety)
    log="$out/safety.log"
    status="$(run_tlc "$module.cfg" "$log")"
    cat "$log"
    echo
    echo "TLC salió con $status: $(verdict "$log"). Log en $log"
    ;;
  each)
    one_by_one "$module.cfg" INVARIANTS invariante
    ;;
  liveness)
    one_by_one "${module}Liveness.cfg" PROPERTIES propiedad
    ;;
  *)
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
