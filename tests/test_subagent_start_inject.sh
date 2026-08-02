# tests/test_subagent_start_inject.sh
set -u
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$SKILL/hooks/subagent-start-inject.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# Case A: cwd inside a project with context/ -> inject lean payload (entry point + counts, NO decision titles).
mkdir -p "$TMP/proj/context/decisions"
mkdir -p "$TMP/proj/context/open-questions"
cat > "$TMP/proj/context/index.html" <<'EOF'
<html><head><title>proj ctx</title></head></html>
EOF
cat > "$TMP/proj/context/config.json" <<'EOF'
{ "projectName": "proj" }
EOF
# Seed 2 open decisions with known titles — these must NOT appear in output.
cat > "$TMP/proj/context/decisions/dec-001.html" <<'EOF'
<html><head>
<meta name="title" content="Use PostgreSQL for storage">
<meta name="status" content="open">
</head></html>
EOF
cat > "$TMP/proj/context/decisions/dec-002.html" <<'EOF'
<html><head>
<meta name="title" content="Deploy on Kubernetes clusters">
<meta name="status" content="open">
</head></html>
EOF
# Seed 1 open question
cat > "$TMP/proj/context/open-questions/oq-001.html" <<'EOF'
<html><head><title>q1</title></head></html>
EOF
mkdir -p "$TMP/proj/sub/dir"
A="$(printf '{"hook_event_name":"SubagentStart","cwd":"%s/proj/sub/dir"}' "$TMP" | FIRSTMATE_HOME="$TMP/nofm" bash "$HOOK")"
echo "$A" | grep -q 'hookSpecificOutput' || { echo "FAIL A: no hookSpecificOutput"; exit 1; }
echo "$A" | grep -q "$TMP/proj/context/index.html" || { echo "FAIL A: project entry point not injected"; exit 1; }
echo "$A" | grep -q 'decisions' || { echo "FAIL A: counts line missing 'decisions'"; exit 1; }
echo "$A" | grep -q 'open questions' || { echo "FAIL A: counts line missing 'open questions'"; exit 1; }
echo "$A" | grep -q 'see' || { echo "FAIL A: counts line missing 'see'"; exit 1; }
echo "$A" | grep -q 'Use PostgreSQL for storage' && { echo "FAIL A: decision title dumped (should be lean)"; exit 1; }
echo "$A" | grep -q 'Deploy on Kubernetes clusters' && { echo "FAIL A: decision title dumped (should be lean)"; exit 1; }
echo "$A" | python3 -c "import json,sys;json.load(sys.stdin)" || { echo "FAIL A: not valid JSON"; exit 1; }

# Case B: cwd NOT in a project, but global instance exists -> inject global registry.
mkdir -p "$TMP/fm/context"
cat > "$TMP/fm/context/index.html" <<'EOF'
<html><head><title>fm</title></head></html>
EOF
cat > "$TMP/fm/context/project-registry.html" <<'EOF'
<html><body><section id="projects"><article class="project">
eco_timing | /p/eco | dash | active
</article></section></body></html>
EOF
B="$(printf '{"hook_event_name":"SubagentStart","cwd":"%s"}' "/tmp" | FIRSTMATE_HOME="$TMP/fm" bash "$HOOK")"
echo "$B" | grep -q "eco_timing" || { echo "FAIL B: global registry not injected on fallback"; exit 1; }
echo "$B" | python3 -c "import json,sys;json.load(sys.stdin)" || { echo "FAIL B: fallback not valid JSON"; exit 1; }

# Case C: no project, no global -> silent no-op.
C="$(printf '{"hook_event_name":"SubagentStart","cwd":"%s"}' "/tmp" | FIRSTMATE_HOME="$TMP/none" bash "$HOOK")"
[ -z "$C" ] || { echo "FAIL C: expected empty output, got: $C"; exit 1; }

echo "PASS"
