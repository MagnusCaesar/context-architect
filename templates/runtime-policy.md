# Runtime Hardening Policy

This context architecture can enforce workflow rules in scripts, but real file
protection requires an external boundary.

## Required Boundary

Run hardening as one of:

- `root`
- an elevated admin user
- another Unix user that the agent process cannot control

If the agent runs as the same user that can execute `chattr -a`, `chmod`, edit
scripts, or rewrite protected files, hardening is advisory only.

## Protected Files

- `context/ledger-events.ndjson`: append-only audit source
- `context/security.json` if present, otherwise permission fields in
  `context/config.json`
- `context/scripts/`: deterministic authority scripts

## Denied Commands For Agent Runtime

The agent sandbox should deny:

- `rm`
- `chmod`
- `chown`
- `chattr`
- `setfacl`
- `sudo`
- `dd`
- `truncate`

It should also deny shell redirection or arbitrary writes to protected files
except through approved scripts.

## Hardening Commands

From outside the agent runtime:

```bash
context/scripts/harden-ledger.sh context
```

Then verify from inside the agent runtime:

```bash
python context/scripts/check-hardening.py --json
```

Expected strong state:

- `ledger_append_only: true`
- protected authority files not writable by the agent process
- runtime sandbox denies `chattr -a`, `chmod`, and destructive commands
