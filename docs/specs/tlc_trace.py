#!/usr/bin/env python3
"""Resume la traza de un log de TLC: un paso por línea, con la acción y solo lo que cambió.

    python3 docs/specs/tlc_trace.py <log de TLC> [--hide var1,var2]
"""

from __future__ import annotations

import argparse
import re
import sys

STATE_RE = re.compile(r"^State (\d+): <(\w[\w ]*?)(?: line .*)?>$")
LASSO_RE = re.compile(r"^(?:State \d+: )?(Stuttering|Back to state:? ?\d+.*)$")
VAR_RE = re.compile(r"^/\\ (\w+) = (.*)$")


def parse_trace(lines: list[str]) -> tuple[str, list[tuple[str, dict[str, str]]]]:
    """Devuelve (motivo de la violación, [(acción, variables)]) del primer contraejemplo."""
    reason = next((ln for ln in lines if ln.startswith("Error: ") and "violated" in ln), "")
    states: list[tuple[str, dict[str, str]]] = []
    current: dict[str, str] | None = None
    last_var: str | None = None
    for raw in lines:
        line = raw.rstrip("\n")
        match = STATE_RE.match(line)
        if match:
            current = {}
            states.append((match.group(2), current))
            last_var = None
            continue
        lasso = LASSO_RE.match(line)
        if lasso:
            states.append((lasso.group(1), current or {}))
            break
        if current is None:
            continue
        var = VAR_RE.match(line)
        if var:
            last_var = var.group(1)
            current[last_var] = var.group(2)
        elif line.startswith("   ") and last_var is not None:
            current[last_var] += " " + line.strip()
        elif not line.strip():
            last_var = None
    return reason.removeprefix("Error: "), states


def summarize(reason: str, states: list[tuple[str, dict[str, str]]], hide: set[str]) -> str:
    if not states:
        return "No hay traza en el log."
    out = [reason]
    previous: dict[str, str] = {}
    for index, (action, values) in enumerate(states, start=1):
        changed = {
            k: v for k, v in sorted(values.items()) if previous.get(k) != v and k not in hide
        }
        if index == 1:
            changed = {k: v for k, v in changed.items() if k in ("skill", "order")}
        detail = ", ".join(f"{k} = {v}" for k, v in changed.items())
        if action.startswith(("Stuttering", "Back to state")):
            out.append(f"{index:>2}. {action} (el comportamiento sigue así para siempre)")
            break
        out.append(f"{index:>2}. {action:<16} {detail}")
        previous = values
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log")
    parser.add_argument("--hide", default="", help="variables que no se muestran, por comas")
    args = parser.parse_args()
    with open(args.log, encoding="utf-8") as fh:
        reason, states = parse_trace(fh.readlines())
    print(summarize(reason, states, {h for h in args.hide.split(",") if h}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
