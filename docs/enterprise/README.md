# Styx Enterprise documentation

- [System design](design.md) - intent, constraints, architecture, decisions D01-D60 (Accepted 2026-11-09)
- [Roadmap](design.md#6-roadmap) - six phases with exit criteria
- [Architecture decision records](adr/README.md) - one ADR per decision, all Accepted 2026-11-09 (ADR-0045 superseded by ADR-0060)
- [Control matrix](control-matrix.md) - NIST 800-53 Rev 5 Moderate skeleton for the SSP/eMASS
- [Component and license register](component-register.md) - third-party libraries, images, charts and apt apps with license, scope and cost; how to update it is at the top (CM-8, SA-4)
- [Full-site restore runbook](runbooks/full-site-restore.md) - rebuild from IaC and offsite data, RTO 8 h (CP-9, CP-10, R03)
- [OpenBao and External Secrets runbook](runbooks/openbao.md) - install, init, static seal rotation, CA renewal, ESO onboarding, snapshot restore (SC-12, IA-5)
- [DMZ HAProxy pair runbook](runbooks/dmz-haproxy.md) - install, cert rotation, failover test, header verification (SC-7, SC-8, SC-23)
- [Backend required environment](runbooks/backend-required-env.md) - `JWT_SECRET` (required on Postgres), `DATABASE_URL`, `LEADER_DATABASE_URL`
- [RKE2 node IaC](../../deploy/rke2/README.md) - Ansible for 3 HA servers and 8 agents (CIS, pinned version, Cilium CNI); not for accredited environments yet
