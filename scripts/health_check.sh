#!/usr/bin/env bash
# PIP-II Virtual Accelerator — system health check.
# Run anywhere the stack is deployed:  ./scripts/health_check.sh  (or: make status)
# Uses the running containers, so it needs no host Python/venv.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
[ -f .env ] && set -a && . ./.env && set +a      # pick up per-host WEBAPP_MODE/iface

PREFIX="${PIP2VA_PV_PREFIX:-SPARK}"
HOSTIP="$(hostname -I 2>/dev/null | awk '{print $1}')"
IFACE="${EPICS_HOST_INTERFACE:-$(ip -o addr show 2>/dev/null | awk -v ip="$HOSTIP" '$0 ~ ip {print $2; exit}')}"

if [ -t 1 ]; then G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; C=$'\033[36m'; D=$'\033[2m'; N=$'\033[0m'
else G=''; R=''; Y=''; C=''; D=''; N=''; fi
FAIL=0; WARN=0
ok()   { printf "  ${G}✓${N} %s\n" "$1"; }
bad()  { printf "  ${R}✗ %s${N}\n" "$1"; FAIL=$((FAIL+1)); }
warn() { printf "  ${Y}! %s${N}\n" "$1"; WARN=$((WARN+1)); }
info() { printf "  ${D}%s${N}\n" "$1"; }
hdr()  { printf "\n${C}== %s ==${N}\n" "$1"; }

dc()  { docker compose "$@" 2>/dev/null; }
rc()  { docker compose exec -T redis redis-cli "$@" 2>/dev/null; }

printf "${C}PIP-II VA health check${N}  ${D}host=%s  iface=%s  prefix=%s${N}\n" \
       "${HOSTIP:-?}" "${IFACE:-?}" "$PREFIX"

# ---- 1. services ------------------------------------------------------
hdr "Services"
PS="$(dc ps --format '{{.Name}}\t{{.Status}}')"
if [ -z "$PS" ]; then
    bad "docker compose not running / no services (is Docker up? right dir?)"
else
    UP=0; TOT=0
    while IFS=$'\t' read -r name status; do
        [ -z "$name" ] && continue
        TOT=$((TOT+1))
        case "$status" in
            Up*) UP=$((UP+1)) ;;
            *)   bad "${name#pip2va-}  ($status)" ;;
        esac
    done <<< "$PS"
    [ "$UP" -eq "$TOT" ] && ok "all $TOT services up" || warn "$UP/$TOT services up"
fi

# ---- 2. machine state -------------------------------------------------
hdr "Machine"
if ! rc ping >/dev/null 2>&1; then
    bad "redis unreachable — cannot read machine state"
else
    W="$(rc hget state:beam w_out)"; T="$(rc hget state:beam transmission)"
    PERMIT="$(rc get state:mps.permit)"
    if [ -z "$W" ]; then
        bad "no beam state in redis (services not seeded? try 'make reset')"
    else
        Wf=$(printf '%.0f' "$W" 2>/dev/null); Tp=$(awk "BEGIN{printf \"%.2f\", $T*100}" 2>/dev/null)
        if [ "${Wf:-0}" -ge 700 ] && [ "$PERMIT" = "1" ]; then
            ok "W=${Wf} MeV  T=${Tp}%  permit=ON"
        elif [ "$PERMIT" != "1" ]; then
            bad "permit DOWN (W=${Wf} MeV) — trip or leftover fault; try 'make reset'"
        else
            warn "W=${Wf} MeV  T=${Tp}%  (energy low)"
        fi
    fi
    # active injected faults
    NF="$(rc --scan --pattern 'fault:*' 2>/dev/null | grep -c . )"
    [ "${NF:-0}" -gt 0 ] && warn "$NF active fault:* keys (injected faults present)" || ok "no injected faults"
    # last trip event
    LT="$(rc xrevrange stream:mps.events + - COUNT 8 | tr '\n' ' ' | grep -o 'trip[^_]*' | head -1)"
    [ -n "$LT" ] && info "recent event: ${LT}"
fi

# ---- 3. telemetry streams (are the sims publishing?) ------------------
hdr "Telemetry streams"
stream_live() {   # $1 stream, $2 max-wait-seconds
    local a b
    a="$(rc xrevrange "stream:$1" + - COUNT 1 | head -1)"
    sleep "${2:-2}"
    b="$(rc xrevrange "stream:$1" + - COUNT 1 | head -1)"
    [ -n "$a" ] && [ "$a" != "$b" ]
}
for s in bpm.orbit blm.losses rf.cavity magnet.readback toroid.current; do
    if stream_live "$s" 2; then ok "$s  live"
    elif [ -n "$(rc xrevrange "stream:$s" + - COUNT 1 2>/dev/null)" ]; then bad "$s  STALE (service crashed? check 'docker compose logs ${s%%.*}-sim')"
    else bad "$s  empty"; fi
done
# beam.deep is intentionally throttled (~0.25 Hz) — allow a longer window
if stream_live beam.deep 6; then ok "beam.deep  live (throttled ~0.25 Hz)"
else warn "beam.deep  no update in 6s (slow deep pass or idle)"; fi

# ---- 4. EPICS PVA gateway ---------------------------------------------
hdr "EPICS (PVA)"
if dc ps --format '{{.Name}}' | grep -q epics-gateway; then
    PVW="$(dc exec -T epics-gateway python -c "
from p4p.client.thread import Context
try: print('%.1f' % float(Context('pva').get('${PREFIX}:PIP2:BEAM:W', timeout=8)))
except Exception as e: print('ERR')" 2>/dev/null | tail -1)"
    if [ "$PVW" != "ERR" ] && [ -n "$PVW" ]; then
        ok "PVA serving  ${PREFIX}:PIP2:BEAM:W = ${PVW} MeV  (multicast 239.128.1.6@${IFACE})"
    else
        bad "PVA server not answering (check EPICS_HOST_INTERFACE=${IFACE:-unset} in .env)"
    fi
    # LLM RPC PV present?
    dc exec -T epics-gateway python -c "print('ok')" >/dev/null 2>&1 && \
        info "RPC:  pvcall ${PREFIX}:AI:ASK query='...'  (LLM, use -w 180)"
else
    warn "epics-gateway not running (WEBAPP_MODE build still includes it)"
fi

# ---- 5. AI / Ollama ---------------------------------------------------
hdr "AI (Ollama)"
OLURL="${PIP2VA_OLLAMA_URL:-http://localhost:11434}"
if curl -s -m3 "$OLURL/api/tags" >/dev/null 2>&1; then
    HASM="$(curl -s -m3 "$OLURL/api/tags" | grep -c 'pip2va-expert')"
    [ "${HASM:-0}" -gt 0 ] && ok "ollama up, pip2va-expert present" || warn "ollama up but pip2va-expert missing (run bake_expert.py)"
    # GPU vs CPU: compare size_vram to size on any loaded model
    PS="$(curl -s -m3 "$OLURL/api/ps")"
    if echo "$PS" | grep -q size_vram; then
        GPU="$(echo "$PS" | tr ',' '\n' | grep -E 'size"|size_vram' | tr -d ' "' | head -2)"
        SZ=$(echo "$PS" | grep -o '"size":[0-9]*' | head -1 | grep -o '[0-9]*')
        VR=$(echo "$PS" | grep -o '"size_vram":[0-9]*' | head -1 | grep -o '[0-9]*')
        if [ -n "$VR" ] && [ "${VR:-0}" -gt 0 ] && [ "${VR:-0}" -ge $(( ${SZ:-1} * 9 / 10 )) ]; then
            ok "model on GPU ($(( VR/1000000000 )) GB VRAM) — fast"
        else
            bad "model on CPU/partial (vram=$(( ${VR:-0}/1000000000 ))GB of $(( ${SZ:-0}/1000000000 ))GB) — SLOW; needs --gpus all + ollama>=0.30"
        fi
    else
        info "no model resident (loads on first query; set OLLAMA_KEEP_ALIVE=-1 to keep warm)"
    fi
else
    warn "ollama not reachable at $OLURL (AI + code-index disabled)"
fi

# ---- 6. code-RAG index ------------------------------------------------
hdr "Code-RAG"
IDX="$HOME/.pip2va/studies/code_index.npz"
if [ -f "$IDX" ]; then
    ok "code index present ($(du -h "$IDX" | cut -f1)) — AI can answer implementation questions"
else
    warn "code index missing — run 'make code-index' (AI works, no code answers)"
fi

# ---- summary ----------------------------------------------------------
hdr "Summary"
if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
    printf "  ${G}ALL SYSTEMS GO${N}\n"; exit 0
elif [ "$FAIL" -eq 0 ]; then
    printf "  ${Y}OK with %d warning(s)${N}\n" "$WARN"; exit 0
else
    printf "  ${R}%d problem(s), %d warning(s)${N} — see ✗ lines above\n" "$FAIL" "$WARN"; exit 1
fi
