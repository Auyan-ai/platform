#!/usr/bin/env python3
"""Compone el bloque Markdown de "Evidencia en vivo" para el cuerpo de un PR.

Lee lo que ya dejaron inbound.sh, dump.sh y trace.sh (o sim-dump.sh, para corridas del simulador)
en evidence/, enmascara emails y teléfonos
y, si le pasas capturas o vídeo, los sube a la rama huérfana `verify-evidence` para que se vean en el PR.
No lee .env.staging ni imprime secretos.
"""
import argparse
import base64
import glob
import json
import os
import re
import subprocess
import sys

VERIFY_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
EVID_DIR = os.path.join(VERIFY_DIR, "evidence")
BRANCH = "verify-evidence"
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif"}
VID_EXT = {".webm", ".mp4"}
MAX_REPLY = 1200
MAX_SECTION = 2500

EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
DATETIME = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}(?::?\d{2})?|Z)?)?")
DECIMAL = re.compile(r"(?<![\w.])\d+\.\d+(?![\w.])")
PHONE = re.compile(r"(?<![\w.])[+(]?\d[\d ().-]{6,}\d(?!\w)")


def mask(text: str) -> str:
    """Enmascara emails (a***@dominio) y teléfonos (solo quedan los 2 últimos dígitos)."""
    text = EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    keep: list[str] = []

    def stash(m: re.Match) -> str:
        keep.append(m.group(0))
        return f"\x00{len(keep) - 1}\x00"

    text = DECIMAL.sub(stash, DATETIME.sub(stash, UUID.sub(stash, text)))

    def phone(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return m.group(0) if len(digits) < 9 else "[tel ***" + digits[-2:] + "]"

    text = PHONE.sub(phone, text)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], text)


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def newest(pattern: str, must_contain: str = "") -> str | None:
    for path in sorted(glob.glob(os.path.join(EVID_DIR, pattern)), reverse=True):
        if not must_contain or must_contain in read(path):
            return path
    return None


def parse_inbound(path: str) -> dict:
    raw = read(path)
    payload = re.search(r"payload: (\{.*\})", raw)
    http = re.search(r"HTTP (\d+)", raw)
    body = raw[http.start():] if http else raw
    start, end = body.find("{"), body.rfind("}")
    resp = json.loads(body[start:end + 1]) if start >= 0 else {}
    sent = json.loads(payload.group(1)) if payload else {}
    return {"sent": sent.get("content", ""), "tenant": sent.get("tenant_slug", ""), "resp": resp,
            "http": http.group(1) if http else "?"}


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "\n… (recortado)"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=VERIFY_DIR).stdout.strip()


def gh(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, input=stdin)


def ensure_branch(repo: str) -> None:
    if gh("api", f"repos/{repo}/git/ref/heads/{BRANCH}").returncode == 0:
        return
    seed = {"tree": [{"path": "README.md", "mode": "100644", "type": "blob",
                      "content": "Capturas de /verify enlazadas desde los PRs. Solo staging o Marea.\n"}]}
    tree = json.loads(gh("api", "-X", "POST", f"repos/{repo}/git/trees", "--input", "-", stdin=json.dumps(seed)).stdout)["sha"]
    msg = "chore: rama huérfana de evidencias de /verify"
    commit = json.loads(gh("api", "-X", "POST", f"repos/{repo}/git/commits", "--input", "-",
                           stdin=json.dumps({"message": msg, "tree": tree, "parents": []})).stdout)["sha"]
    r = gh("api", "-X", "POST", f"repos/{repo}/git/refs", "--input", "-",
           stdin=json.dumps({"ref": f"refs/heads/{BRANCH}", "sha": commit}))
    if r.returncode != 0:
        sys.exit(f"no pude crear la rama {BRANCH}: {r.stderr.strip()}")


def upload(path: str, repo: str, folder: str) -> str:
    """Sube un archivo de evidence/ a la rama huérfana y devuelve su URL visible en GitHub."""
    real = os.path.realpath(path)
    ext = os.path.splitext(real)[1].lower()
    if not real.startswith(EVID_DIR + os.sep) or ext not in IMG_EXT | VID_EXT:
        sys.exit(f"solo subo imágenes o vídeo de {EVID_DIR}: {path}")
    ensure_branch(repo)
    dest = f"{folder}/{os.path.basename(real)}"
    with open(real, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    r = gh("api", "-X", "PUT", f"repos/{repo}/contents/{dest}", "--input", "-",
           stdin=json.dumps({"message": f"chore: evidencia {dest}", "branch": BRANCH, "content": content}))
    if r.returncode != 0 and "already exists" not in r.stderr and "sha" not in r.stderr:
        sys.exit(f"falló la subida de {dest}: {r.stderr.strip()}")
    return f"https://github.com/{repo}/blob/{BRANCH}/{dest}?raw=true"


def console_errors(png: str) -> str:
    txt = os.path.splitext(png)[0] + ".txt"
    if not os.path.exists(txt):
        return ""
    marker = "--- errores de consola ---"
    body = read(txt)
    n = len(body.split(marker)[1].strip().splitlines()) if marker in body else 0
    return f"{n} errores de consola"


def sections(dump: str) -> list[tuple[str, str]]:
    parts = re.split(r"^## (\w+)\n", dump, flags=re.M)
    return [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


def sim_run(run_id: str) -> tuple[dict, dict[str, str]]:
    dump = newest(f"*-sim-{run_id}.txt")
    if not dump:
        sys.exit(f"no hay evidence/*-sim-{run_id}.txt: corre sim-dump.sh {run_id} primero")
    parts = dict(sections(read(dump)))
    row = next((line for line in parts.get("run", "").splitlines() if line.startswith("{")), None)
    if row is None:
        sys.exit(f"{dump} no tiene la fila de simulation_runs")
    return json.loads(row), parts


def compose_simulation(run_ids: list[str]) -> str:
    runs = [sim_run(r) for r in run_ids]
    tenants = sorted({info["tenant"] for info, _ in runs})
    out = [f"**Staging, tenant `{', '.join(tenants)}`, commit `{git('rev-parse', '--short', 'HEAD')}`.** "
           "Corridas del simulador (conversaciones `is_simulation`), sin clientes reales.", "",
           "| Escenario | Estado | Judge | Terminación | Turnos | Mensajes in/out | Coste | Traza LangSmith |",
           "|---|---|---|---|---|---|---|---|"]
    details = []
    for info, parts in runs:
        tid = info.get("langsmith_trace_id")
        judge = "-" if info.get("judge") is None else f"{float(info['judge']):.1f}"
        cost = "-" if info.get("cost_cents") is None else f"${float(info['cost_cents']) / 100:.4f}"
        out.append(f"| {info['scenario']} | {info['status']} | {judge} | {info['termination_reason']} | "
                   f"{info['turns_count']} | {info['inbound']}/{info['outbound']} | {cost} | `{tid or '-'}` |")
        trace = newest(f"*-trace-{tid}.txt") if tid else None
        body = [f"Run `{info['id']}`, conversación `{info['conversation_id']}`.", ""]
        body += ["```", "\n".join(read(trace).strip().splitlines()[:2]) if trace else "sin trace.sh para esta corrida", "```"]
        for name in ("messages", "skills", "escalations"):
            if parts.get(name):
                body += ["", f"Supabase: {name}", "", "```", clip(parts[name], MAX_SECTION), "```"]
        details += ["", f"<details><summary>{info['scenario']}</summary>", "", *body, "", "</details>"]
    return mask("\n".join(out + details)) + "\n"


def compose(args: argparse.Namespace) -> str:
    conv = args.conversation_id
    inbound = newest("*-inbound-*.txt", conv)
    if not inbound:
        sys.exit(f"no hay evidence/*-inbound-*.txt con la conversación {conv}: corre inbound.sh primero")
    info = parse_inbound(inbound)
    resp = info["resp"]
    tid = args.trace_id or resp.get("trace_id")
    dump = newest(f"*-db-{conv}.txt")
    trace = newest(f"*-trace-{tid}.txt") if tid else None
    sha = git("rev-parse", "--short", "HEAD")
    out = [f"**Staging, tenant `{info['tenant']}`, commit `{sha}`.** Datos de prueba (`VERIFY bot`), sin clientes reales.", ""]
    out += ["| | |", "|---|---|",
            f"| Decisión | `{resp.get('decision')}` (HTTP {info['http']}) |",
            f"| Conversación | `{conv}` |",
            f"| Traza LangSmith | `{tid}` (proyecto `auyan-staging`) |"]
    if resp.get("escalation_reason"):
        out.append(f"| Motivo de escalado | {resp['escalation_reason']} |")
    out += ["", "**Mensaje enviado**", "", f"> {info['sent']}", "", "**Respuesta del agente**", ""]
    out += ["> " + line for line in clip(resp.get("response_text") or "(sin respuesta)", MAX_REPLY).splitlines()]
    if trace:
        out += ["", "**Traza** (`trace.sh`)", "", "```", "\n".join(read(trace).strip().splitlines()[:2]), "```"]
    else:
        out += ["", "**Traza**: sin `trace.sh` guardado para este id."]
    if dump:
        for name, body in sections(read(dump)):
            if body:
                out += ["", f"<details><summary>Supabase: {name}</summary>", "", "```", clip(body, MAX_SECTION), "```", "",
                        "</details>"]
    else:
        out += ["", "**Supabase**: sin `dump.sh` guardado para esta conversación."]
    text = mask("\n".join(out))
    out = []
    if args.media:
        repo = args.repo or json.loads(gh("repo", "view", "--json", "nameWithOwner").stdout)["nameWithOwner"]
        folder = re.sub(r"[^A-Za-z0-9._-]+", "-", args.folder or git("rev-parse", "--abbrev-ref", "HEAD"))
        out += ["", "**Capturas y vídeo**"]
        for path in args.media:
            url = path if args.no_upload else upload(path, repo, folder)
            name, ext = os.path.basename(path), os.path.splitext(path)[1].lower()
            note = console_errors(path) if ext in IMG_EXT else ""
            out += ["", (f"![{name}]({url})" if ext in IMG_EXT else f"[vídeo: {name}]({url})") + (f" ({note})" if note else "")]
    return "\n".join([text, *out]) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(
        description="Compone el bloque de evidencia en vivo para un PR a partir de evidence/ (emails y teléfonos enmascarados).",
        epilog="Ejemplo: evidence-md.py <conversation_id> --media evidence/<ts>-conversaciones.png > /tmp/evidencia.md")
    p.add_argument("conversation_id", nargs="?", help="uuid de la conversación (lo imprime inbound.sh)")
    p.add_argument("--simulation-run-id", nargs="+", metavar="RUN_ID",
                   help="corridas del simulador (las imprime run_simulator); lee lo que guardó sim-dump.sh")
    p.add_argument("--trace-id", help="por defecto el de la respuesta de inbound.sh")
    p.add_argument("--media", nargs="*", default=[], metavar="ARCHIVO",
                   help="capturas (.png/.jpg) o vídeo (.webm/.mp4) de evidence/; se suben a la rama verify-evidence")
    p.add_argument("--no-upload", action="store_true", help="no subir: deja la ruta local en el enlace")
    p.add_argument("--repo", help="owner/repo (por defecto el del checkout)")
    p.add_argument("--folder", help="carpeta dentro de verify-evidence (por defecto la rama actual)")
    args = p.parse_args()
    if args.simulation_run_id:
        for run_id in args.simulation_run_id:
            if not re.fullmatch(r"[0-9a-f-]{36}", run_id):
                sys.exit(f"simulation_run_id no es un uuid: {run_id}")
        sys.stdout.write(compose_simulation(args.simulation_run_id))
        return
    if args.conversation_id is None:
        sys.exit("falta conversation_id o --simulation-run-id")
    if not re.fullmatch(r"[0-9a-f-]{36}", args.conversation_id):
        sys.exit("conversation_id no es un uuid")
    sys.stdout.write(compose(args))


if __name__ == "__main__":
    main()
