# Deploying Hawkeye

```
https://fly-hawkeye.com      → AWS Amplify      → React frontend (frontend/)
https://api.fly-hawkeye.com  → EC2 (nginx → uvicorn :8000) → FastAPI backend (backend/)
                                                             → DynamoDB
```

Local dev is unchanged: `npm run dev` + `uvicorn api:app --reload --port 8000` still talk to each other on localhost.

| File | What it is |
|---|---|
| `setup_server.sh` | One command that installs everything on the server |
| `hawkeye-api.service` | Keeps the API running (systemd) |
| `nginx-api.fly-hawkeye.com.conf` | Public entrance for `api.fly-hawkeye.com` |
| `hawkeye.env.example` | Server settings (region, table names) |
| `iam-policy.json` | Permissions the server needs (DynamoDB, Lambda) |

---

## 1. IAM role for the server (once)

The server gets DynamoDB access from a role, so **no AWS keys go on the server**.

1. **IAM → Policies → Create policy → JSON**, paste `iam-policy.json`, name it `HawkeyeApiPolicy`.
2. **IAM → Roles → Create role** → trusted entity **AWS service → EC2** → attach `HawkeyeApiPolicy` → name it `HawkeyeApiRole`.

## 2. Launch the EC2 instance

**EC2 → Launch instance**, in the **same region as your DynamoDB tables**:

- **Name:** `hawkeye-api`
- **AMI:** Ubuntu Server 24.04 LTS
- **Instance type:** `t3.medium` (4 GB RAM — YOLO needs it)
- **Key pair:** create one, download the `.pem` (keep it safe)
- **Network → Security group:** allow **SSH (22) from My IP**, **HTTP (80)** and **HTTPS (443)** from anywhere
- **Storage:** 20 GB (PyTorch is big)
- **Advanced details → IAM instance profile:** `HawkeyeApiRole`

Then **EC2 → Elastic IPs → Allocate → Associate** it with the instance, so the IP never changes.

## 3. Set up the server

```bash
chmod 400 ~/Downloads/hawkeye-key.pem
ssh -i ~/Downloads/hawkeye-key.pem ubuntu@<ELASTIC_IP>
```

On the server:

```bash
git clone https://github.com/Lord-Helix07/hawkeye.git ~/hawkeye
bash ~/hawkeye/backend/deploy/setup_server.sh
```

> If the repo is private, `git clone` will ask for a username and a **GitHub personal access token** (not your password).

Check `/etc/hawkeye/hawkeye.env` has the right `AWS_REGION` (`sudo nano /etc/hawkeye/hawkeye.env`, then `sudo systemctl restart hawkeye-api`).

Test from your laptop: `http://<ELASTIC_IP>/docs` should show the API docs.

## 4. Point the domain at it (after fly-hawkeye.com shows "Successful")

**Route 53 → Hosted zones → fly-hawkeye.com → Create record**

- Record name: `api`
- Type: `A`
- Value: `<ELASTIC_IP>`

Wait a few minutes, then on the server:

```bash
sudo certbot --nginx -d api.fly-hawkeye.com
```

(Give it your email, agree, choose redirect.) Certbot renews the certificate automatically.

Test: **https://api.fly-hawkeye.com/docs**

## 5. Frontend on Amplify

1. **Amplify → Create new app → GitHub** → pick the repo and branch.
2. Tick **"My app is a monorepo"**, app root: `frontend`. Build: `npm run build`, output: `dist`.
3. **Hosting → Rewrites and redirects → Manage → add:**
   - Source: `</^[^.]+$|\.(?!(css|js|png|svg|jpg|jpeg|gif|ico|json|webp|txt|woff2?)$)([^.]+$)/>`
   - Target: `/index.html`
   - Type: `200 (Rewrite)`

   (Without this, refreshing a page like `/dashboard` gives a 404.)
4. **Hosting → Custom domains → Add domain** → `fly-hawkeye.com` → include `www` → Amplify creates the DNS records and HTTPS certificate.

The API address comes from `frontend/.env.production` (`https://api.fly-hawkeye.com`), so no Amplify env var is needed.

---

## Updating after code changes

- **Frontend:** push to GitHub — Amplify rebuilds automatically.
- **Backend:**
  ```bash
  ssh -i ~/Downloads/hawkeye-key.pem ubuntu@<ELASTIC_IP>
  cd ~/hawkeye && git pull && bash backend/deploy/setup_server.sh
  ```

## Troubleshooting

| Problem | Check |
|---|---|
| API won't start | `sudo journalctl -u hawkeye-api -n 50` |
| 502 Bad Gateway | API crashed/not started — see above |
| `AccessDeniedException` from DynamoDB | IAM role not attached, or wrong `AWS_REGION` |
| CORS error in browser | Frontend origin must be `fly-hawkeye.com`, `www.`, `*.amplifyapp.com`, or localhost (see `backend/api.py`) |
| certbot fails | `api.fly-hawkeye.com` A record not live yet — `dig api.fly-hawkeye.com` should show the Elastic IP |

## Cost

`t3.medium` ≈ $30/month running 24/7. **Stop the instance** (EC2 → Instance state → Stop) when not demoing — you only pay for storage (~$2/month) while stopped. The Elastic IP is free while attached to a running instance (~$3.60/month otherwise).
