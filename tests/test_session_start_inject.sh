set -u
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$SKILL/hooks/session-start-inject.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Build a fake firstmate home with a registry page
mkdir -p "$TMP/context"
cat > "$TMP/context/index.html" <<'EOF'
<html><head><title>firstmate</title></head><body></body></html>
EOF
cat > "$TMP/context/project-registry.html" <<'EOF'
<html><body>
<article class="project" id="eco_timing">
  eco_timing | /p/eco_timing/context | timing dash | active
</article>
<article class="project" id="sdc_copilot">sdc_copilot | /p/sdc/context | sdc dash | active</article>
</body></html>
EOF

OUT="$(FIRSTMATE_HOME="$TMP" echo '{"hook_event_name":"SessionStart","cwd":"/tmp"}' | FIRSTMATE_HOME="$TMP" bash "$HOOK")"
echo "$OUT" | grep -q "eco_timing" || { echo "FAIL: multi-line article not injected"; exit 1; }
echo "$OUT" | grep -q "sdc_copilot" || { echo "FAIL: single-line article not injected"; exit 1; }

# No instance -> silent no-op
OUT2="$(FIRSTMATE_HOME="$TMP/does-not-exist" echo '{"hook_event_name":"SessionStart"}' | FIRSTMATE_HOME="$TMP/does-not-exist" bash "$HOOK")"
[ -z "$OUT2" ] || { echo "FAIL: expected no output when instance absent"; exit 1; }

echo "PASS"
