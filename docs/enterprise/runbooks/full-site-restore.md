# Full-site restore

Restore the Styx database in a new cluster from the offsite barman-cloud
bucket (`deploy/enterprise/objectstore.yaml`). RPO 24 h, RTO 8 h (D37).
Cluster-level detail: [Enterprise Kubernetes](../../operate/kubernetes-enterprise.md).

1. Stand up the cluster and install the operators (CNPG, barman-cloud plugin
   with cert-manager, ESO, Reloader).
2. Recover the escrowed secrets from OpenBao (both escrow sets).
3. Create namespace `styx` and the `styx-db-bucket` Secret.
4. Apply `deploy/enterprise` with `replicas: 1` for the backend.
5. Create a `Cluster` with `bootstrap.recovery` pointing at the `styx-db-offsite` ObjectStore.
6. Verify the restore: wait for the cluster to be healthy, then check `/api/auth/status` and log in.

!!! warning "SSE-C key (step 6)"
    The bucket is written with SSE-C. Recovery reads fail unless
    `SSE_CUSTOMER_KEY` in `styx-db-bucket` is byte-identical to the key used
    for the backups. The key must never change for the life of the backups.
    Take it from the OpenBao escrow (both escrow sets, B1). If the provider
    lacks SSE-C, the fallback is SSE-KMS.
