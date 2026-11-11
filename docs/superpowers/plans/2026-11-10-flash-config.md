# A9 electronic-shutter flash configuration implementation plan

**Goal:** Provide an independent service-mode script for the native Backup
`00020008` / index `45` candidate already described and requested by the user.

**Architecture:** Reuse a9tool identification, bounded Senser transport and
durable journals. Keep a separate exact-payload guard for flash operations;
the PP/Fn guard remains scoped to its existing properties. Default to status,
with explicit apply and journal-based restore commands.

**Scope:** Source delivery in the user-specified project. No camera access,
firmware patch, RAM access, protection changes, or LA-EA5 work. No agents.
Hardware behavior, cold-start adoption and physical triggering remain unproved.

## Files and contracts

- `src/a9tool/flash_config.py`: validate 1024-byte BIN!/FIN! table, enabled=1,
  tag=20160707, count=104, distinct indices 0..106, index45 value0/1. Locate the
  index dynamically. Validate the original Backup checksum and attr=0.
- `src/a9tool/flash_service.py`: status/apply/restore, exact one-shot guard,
  journal before write, repeated baseline check, immediate and saved readback;
  failures stop without retry/save. Restore checks identity, original snapshot,
  payload consistency, and current value against recorded old/target states.
- `src/a9tool/flash.py`: default read-only command-line entry; explicit apply
  and restore, clear reporting of configuration verification only, handle close.
- `src/a9tool/usbdev.py`: optional guard factory and returned guard reference;
  preserve the existing default connection behavior.
- `tests/flash_fakes.py`, `tests/test_flash.py`, `tests/test_connect.py`:
  valid synthetic BK4 data and real vendor packet serialization against an
  in-memory service transport; never enumerate or command physical devices.
- `docs/FLASH.zh-CN.md`, `README.zh-CN.md`: scope, commands, backup paths,
  recovery prerequisites and distinction between saved data and physical flash.

## Execution

- [x] Baseline: `PYTHONPATH=src python -m unittest discover -v`: 87 passed.
- [x] Write and run failing tests for preservation, malformed inputs,
  identity/attribute refusal, prewrite races, failed and mismatched writes,
  save verification, exact-payload guard, and conflict-aware restore.
- [x] Implement the config, guard, transactions and connection injection.
- [x] Implement CLI and source-use instructions; test default read-only behavior.
- [x] Run the complete test suite; verify help without camera access and validate
  the parser on all 11 original factory properties without changing originals.
- [x] Review diff for accidental PP/Fn scope changes, retries, false success
  wording, backups from other bodies, and restoration that overwrites third states.

## Review focus

Target index can move; byte45 is not the index. Preserve padding and unrelated
records. Refuse checksum/metadata drift and ambiguous write results. Consume the
write allowance before sending; enable SAVE only after exact readback. A journal
is recovery material for a reachable service interface, not a boot recovery tool.

## Results

2026-11-10: `PYTHONPATH=src python -m unittest discover -q`: 111 tests passed.
`python -S -m a9tool.flash --help` passed using bundled dependencies.
All 11 factory templates matched their previously verified SHA256; in-memory
transformation changed only byte552 and reversed exactly. Evidence:
`docs/FLASH_FACTORY_VALIDATION_20261110.json`. No changed Backup payload was
written to disk, no camera was accessed, and no hardware claim was validated.
The final diff check found no whitespace errors. Review was performed locally
without agents, per the user's instruction. No exe, commit, push or release.
