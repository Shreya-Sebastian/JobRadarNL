# Deploying the radar on Kubernetes

The application is one image with four roles: `api`, `worker`, `schedule`, `finalize`. Postgres holds the
data, Redis holds the queue, the shared per-host rate limits and the response cache. The Helm chart in
`deploy/helm/radar` runs everything except Postgres.

```
             CronJob scheduler (every 15 min) ──enqueue──► Redis queue ◄──pull── worker pods (3..N, KEDA)
                                                              │                        │
             CronJob finalizer (twice an hour) ──dedup, gauges, bump data version      ▼
                                                              │                    Postgres
             api pods (2..6, HPA on CPU) ◄── Redis response cache + data version   (outside the cluster)
                 ▲
          Ingress (Traefik) + cert-manager TLS
```

## 0. Local, no cluster

```bash
docker compose up --build          # Postgres, Redis, API on :8000, 4 workers, a scheduler loop
```

## 1. Local cluster (Docker Desktop Kubernetes, kind or k3d)

```bash
docker build -t radar:dev .
kind create cluster && kind load docker-image radar:dev          # or: k3d cluster create radar
helm upgrade --install radar deploy/helm/radar -n radar --create-namespace \
  --set image.repository=radar --set image.tag=dev --set image.pullPolicy=Never \
  --set ingress.enabled=false \
  --set database.url="postgresql+psycopg://radar:radar@host.docker.internal:5432/radar"
kubectl -n radar port-forward svc/radar-radar-api 8000:80
```

A Postgres on the host (or `docker run postgres:16-alpine`) is enough for this.

## 2. Production: one AWS server with k3s (techjobsradar.nl, about USD 40 a month)

`deploy/aws` creates one EC2 t3.medium in eu-west-1 with an Elastic IP, a security group (web open, SSH and the
Kubernetes API only from the admin's IP), Postgres on the host with a nightly `pg_dump`, k3s with Traefik and
cert-manager, and Amazon SES for login e-mails with a send-only SMTP user.

1. `aws login`, then `cd deploy/aws && terraform init && terraform apply`.
2. Add the records from `terraform output dns_records` at the registrar: the A record for the site, three DKIM
   CNAMEs and a DMARC TXT for mail.
3. Kubeconfig: `scp ubuntu@<ip>:kubeconfig ~/.kube/radar.yaml` and `export KUBECONFIG=~/.kube/radar.yaml`.
4. `kubectl apply -f deploy/k8s/cluster-issuer.yaml` (after the cert-manager pods are Running).
5. Secrets, in namespace `radar`:
   - `radar-db` with `RADAR_DATABASE_URL` = `terraform output -raw database_url_in_cluster`
   - `radar-smtp` with `RADAR_SMTP_USER` / `RADAR_SMTP_PASSWORD` from the `smtp_user` / `smtp_password` outputs
   - `radar-admin` with `RADAR_ADMIN_TOKEN`
   - `ghcr`, a docker-registry secret for `ghcr.io` with a GitHub token that has `read:packages`
6. Copy the data: open a tunnel (`ssh -N -L 5433:localhost:5432 ubuntu@<ip>`) and run
   `radar copy-db --to "$(terraform output -raw database_url_via_tunnel)"` from the laptop.
7. `helm upgrade --install radar deploy/helm/radar -n radar -f deploy/aws/values-prod.yaml`
8. Login mail: production sends through Resend (`smtp.resend.com`, user `resend`, an API key with sending access,
   the domain verified with Resend's DKIM, MX and SPF records). Amazon SES is set up too, but a new account starts
   in a sandbox that only delivers to verified addresses and needs production access, which AWS may decline.

The image is built by `.github/workflows/image.yml` on every push to main.

## 2b. Alternative: one Hetzner server with k3s (about 5 to 8 euros a month)

1. `cd deploy/terraform && terraform init && terraform apply -var ssh_public_key="$(cat ~/.ssh/id_ed25519.pub)" -var postgres_password=...`
   Creates the server, firewall, k3s, cert-manager, Postgres on the host, and a nightly `pg_dump` cron.
2. Fetch the kubeconfig as printed by `terraform output next_steps`, point a DNS A record at the IP.
3. `kubectl apply -f deploy/k8s/cluster-issuer.yaml`.
4. `kubectl -n radar create secret generic radar-db --from-literal=RADAR_DATABASE_URL="$(terraform output -raw database_url)"`
5. `helm upgrade --install radar deploy/helm/radar -n radar --create-namespace --set ingress.host=YOUR_DOMAIN --set database.existingSecret=radar-db --set config.corsOrigins=https://YOUR_DOMAIN`
6. Seed once: `kubectl -n radar create job --from=cronjob/radar-radar-scheduler seed-1`, then load sources
   with `kubectl -n radar exec deploy/radar-radar-api -- python -m radar.cli register-probed` after copying
   `data/enumerated/probed_*.json` into the pod, or run `radar enumerate` and `radar probe-boards` from a Job.
7. Continuous deployment: add `KUBECONFIG_B64` (base64 of the kubeconfig) as a repository secret and
   `RADAR_HOST` as a repository variable; `.github/workflows/deploy.yml` builds the image to GHCR and runs
   `helm upgrade` on every push to main.

## 3. Scaling knobs

| What | Where | Effect |
|---|---|---|
| More crawl throughput | `worker.replicas`, or `worker.keda.enabled=true` | Workers pull from the queue; KEDA scales 0..30 on queue length |
| Fresher data | `scheduler.schedule`, `config.cadence*Minutes` | High-yield boards hourly, others every 3 or 12 hours |
| More countries | `config.countries=ALL` or `NL,BE,DE` | Same pipeline, every posting with a known country |
| Politeness | `config.hostRateLimits` | Shared per-host budgets across all workers (Workable needs 0.5 rps) |
| API capacity | `api.autoscaling.*`, Redis cache TTL | Responses cached per data version; replicas scale on CPU |
| Observability | `serviceMonitor.enabled=true` | kube-prometheus-stack scrapes `/metrics` on api and workers |

Alerts worth setting in Grafana: `radar_queue_depth{queue="crawl"}` still high 2 hours after a schedule
tick; `increase(radar_fetches_total{status!="ok"}[1h])` above 10 percent of fetches; `radar_live_postings`
dropping more than 20 percent day over day; no `finalize` log line in the last hour.

## 4. Moving to a managed cluster later

The chart does not depend on k3s. On AKS or GKE: set `ingress.className=nginx`, install ingress-nginx,
cert-manager and KEDA, use a managed Postgres URL in the `radar-db` secret, and enable node autoscaling
with a spot pool for workers (`worker` pods tolerate being killed; the job is retried).
