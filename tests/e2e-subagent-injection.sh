# tests/e2e-subagent-injection.sh
# Manual E2E: proves SubagentStart injection reaches a spawned subagent with the
# RIGHT (project-aware) payload. Requires `claude` on PATH. Not run by smoke.sh.
set -u
ECO=/shared/home/vrajagopal/projects/PD/eco_timing
echo "== Project-aware path: spawn a subagent from inside eco_timing =="
( cd "$ECO" && timeout 180 claude -p --include-hook-events \
  "Spawn ONE general-purpose subagent via the Task tool. Instruct it to quote verbatim any PROJECT CONTEXT or entry-point path it sees in its injected context. Report the subagent's reply verbatim." )
echo
echo "Check above: the subagent should quote an entry point ending in /eco_timing/context/index.html"
