# Runbook: Phase 1 exit checklist

Phase 1 exits (design.md §6) when both demos below pass and their evidence is attached to the exit
review. Run both on the real hardware; the kind versions prove the scripts, not the timings.

## 1. HA demo (#103)

`scripts/enterprise/ha_demo.sh` deploys CNPG and three Styx replicas, then:

1. Creates the first admin with the DB-backed setup token, logs in and lists instances.
2. Force-deletes the leader pod, waits for a new leader, repeats login and instance list.
3. Force-deletes the CNPG primary, waits for failover, repeats login and instance list.

Throughout, an in-cluster prober hits `/api/health` every 0.2 s and a sampler reads the leader
advisory lock (`0x5354,1`) from the primary every 2 s.

### Run it

- **CI:** the `kind-spike` workflow runs `scripts/kind/30-ha-demo.sh`. Manual run: Actions >
  kind-spike > Run workflow, `script` = `30-ha-demo.sh`. Evidence is in the `kind-spike-out`
  artifact under `ha-demo/` (`report.txt`, `health.log`, `leaders.log`).
- **Real cluster:** `HA_OUT=./evidence MAX_GAP_S=30 KIND_CLUSTER=<ctx> scripts/enterprise/ha_demo.sh`.
  The script builds and `kind load`s the backend image; on real hardware adapt the image step.

### Pass criteria

| Check | Expected |
|-------|----------|
| Login and instance list | 200 at baseline, after leader kill, after primary kill |
| `/api/health` | 200 except one bounded gap; the longest gap is reported and must be <= `MAX_GAP_S` (30 s) |
| Leaders | never more than one; exactly one in the last sample; zero is allowed only during handover |

Record the reported gap and failover times in the exit review. A gap over the bound fails the
demo; investigate probes (`readinessProbe`) and `LEADER_FENCE_S` before changing the bound.

## 2. Full-site restore (#15)

Run the restore test from [full-site-restore.md](full-site-restore.md) with the #15 harness and
keep its evidence file (schema in #15). Pass: RTO <= 8 h measured per the RTO clock section, CAC
login, desktop launch and priority-user homes restored.

## Exit checklist

- [ ] HA demo green in CI (`kind-spike`) and on real hardware; report and logs attached
- [ ] Health gap and failover times recorded
- [ ] Full-site restore test passed; #15 evidence file attached
- [ ] Open `TBD (owner input)` placeholders in the restore runbook resolved
- [ ] Owner sign-off recorded on the exit issue
