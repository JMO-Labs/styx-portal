# Squid egress runbook

Operate the desktop egress proxy from `deploy/enterprise/squid/` (ADR-0040, ADR-0064). Implemented in code, not deployed. Namespace: `egress-proxy`.

## Add an allowlist host

Allowlist mode (port 3129) uses one shared list for all groups.

1. Add the host to `allowlist.txt` in `deploy/enterprise/squid/allowlist.yaml`. A leading dot covers the domain and its subdomains (`.example.org`).
2. Merge through the normal review, then apply:
   ```bash
   kubectl apply -k deploy/enterprise/squid
   kubectl -n egress-proxy rollout restart deploy/squid
   ```
   The restart is needed because Squid reads the file at start.
3. Check: `curl -x http://squid.egress-proxy.svc.cluster.local:3129 -I https://example.org` from a pod in `styx-instances` labelled `styx.io/egress-mode: allowlist`.

## Change a group's mode

Admin UI: Groups, set the group's egress mode to `category` or `allowlist`. API: `PATCH` the group with `egress_mode`.

- A user in several groups gets the strictest mode: `allowlist` if any of their groups has it.
- The mode is set as a pod label at launch. Running desktops keep their old mode until the user stops and relaunches.
- Cilium sends `allowlist` desktops to port 3129 and all others to 3128 (`deploy/k8s/components/cilium-baseline/README.md`).

## Force a category update

The `squid-categories-update` CronJob runs daily at 03:17 UTC and writes UT1 lists to the `squid-categories` PVC.

```bash
kubectl -n egress-proxy create job --from=cronjob/squid-categories-update categories-now
kubectl -n egress-proxy logs job/categories-now
```

If a download fails the job exits 1 and the old lists stay. Squid expands the lists at start, so restart to apply them:

```bash
kubectl -n egress-proxy rollout restart deploy/squid
```

## Find a hostname in Elastic

In Kibana Discover, pick the `logs-squid.access-*` data view and search, for example:

```
host : "example.org"
```

Each line records time, source IP, host, method, status, action (`TCP_DENIED` means blocked), `port_name` (`category` or `allowlist`) and bytes. Only hostnames are logged; there are no URLs or paths (no SSL-bump). The source IP maps to a user through the Styx audit stream..
