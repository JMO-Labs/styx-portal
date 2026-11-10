# Raft snapshot CronJob (role raft-snapshot): take snapshots, nothing else.
path "sys/storage/raft/snapshot" {
  capabilities = ["read"]
}
