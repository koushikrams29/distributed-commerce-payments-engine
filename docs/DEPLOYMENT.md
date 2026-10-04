# Deploying the live demo

This puts the whole system on the internet at an `https://` address, on a free Oracle Cloud server. You need about an hour, most of it waiting. No prior cloud experience is assumed.

**What you end up with:** one Linux server running every container from this repository. Only HTTPS (and HTTP, which redirects to it) is reachable from the internet; databases, the message broker and the monitoring tools are not. Design and reasoning: [ARCHITECTURE §9](./ARCHITECTURE.md#9-deployment-architecture).

**Cost:** nothing. Oracle's "Always Free" tier includes an ARM server with up to 4 CPU cores and 24 GB of memory. Sign-up asks for a debit or credit card to verify your identity; Oracle places a small temporary hold and refunds it. A free-tier account is not charged unless you upgrade it yourself.

## 1. Create the Oracle Cloud account

1. Go to [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) and choose **Start for free**.
2. Pick your **home region** carefully — it cannot be changed later, and free servers can only be created there. Choose one close to you (for India: *India West (Mumbai)* or *India South (Hyderabad)*).
3. Finish the sign-up, including the card check. Account activation can take a few minutes; wait for the "your account is ready" email.

## 2. Make an SSH key on your computer

An SSH key is how you log in to the server without a password. In PowerShell:

```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\oracle_commerce
```

Press Enter at the passphrase prompts (or set one). This creates two files: `oracle_commerce` (private — never share it) and `oracle_commerce.pub` (public — you give this to Oracle).

## 3. Create the server

In the Oracle Cloud console, open the menu → **Compute** → **Instances** → **Create instance**.

| Setting | Value |
|---|---|
| Name | `commerce-demo` |
| Image | **Canonical Ubuntu 24.04** (choose *Change image*) |
| Shape | *Change shape* → **Ampere** → `VM.Standard.A1.Flex`, **2 OCPUs, 12 GB memory** |
| Networking | *Create new virtual cloud network* and *Create new public subnet*; make sure **Assign a public IPv4 address** is on |
| Add SSH keys | *Upload public key files* → pick `oracle_commerce.pub` |
| Boot volume | leave the default |

Choose **Create**. After a minute or two the instance shows **Running**; copy its **Public IP address**.

> **"Out of capacity"?** Free ARM servers are popular. Try a different *availability domain* in the placement section, try again a few hours later, or start with 1 OCPU / 6 GB (enough for the demo).

## 4. Open ports 80 and 443 in Oracle's firewall

Oracle blocks everything except SSH by default.

1. On the instance page, click the **subnet** name, then the **Default Security List**.
2. **Add Ingress Rules**, twice:
   - Source CIDR `0.0.0.0/0`, IP protocol **TCP**, destination port **80**
   - Source CIDR `0.0.0.0/0`, IP protocol **TCP**, destination port **443**

The server also has its own firewall; the setup script in step 7 opens the same ports there.

## 5. Get a free domain name

HTTPS certificates are issued for names, not bare IP addresses.

1. Go to [duckdns.org](https://www.duckdns.org) and sign in with your GitHub account.
2. Choose a subdomain, e.g. `koushik-commerce` → **add domain**.
3. In the **current ip** box, paste the server's public IP and choose **update ip**.

Your address is now `koushik-commerce.duckdns.org`.

## 6. Log in to the server

```powershell
ssh -i $HOME\.ssh\oracle_commerce ubuntu@<public-ip>
```

Answer `yes` to the fingerprint question the first time. Everything from here on runs **on the server**.

## 7. Install and start everything

```bash
git clone https://github.com/koushikrams29/distributed-commerce-payments-engine.git
cd distributed-commerce-payments-engine
bash scripts/deploy/setup_server.sh
```

The script installs Docker, caps log sizes so the disk never fills, and opens ports 80/443 on the server. When it asks you to, log out (`exit`) and log back in with the same `ssh` command, then:

```bash
cd distributed-commerce-payments-engine
bash scripts/deploy/create_env.sh koushik-commerce.duckdns.org
```

This writes `infra/.env` with freshly generated passwords and prints the logins. **Save them in a password manager** — they are not stored anywhere else. Then start the stack:

```bash
bash scripts/deploy/deploy.sh
```

The first run builds every image on the server and takes 10–20 minutes. It finishes with `Deployed. Open https://koushik-commerce.duckdns.org`.

## 8. Check it works

Open the address in a browser and sign in with the dashboard login that `create_env.sh` printed. To run the same end-to-end test CI runs, from the repository on **your computer**:

```powershell
pip install -r scripts/requirements.txt
$env:DEMO_ADMIN_PASSWORD = "<dashboard password>"
$env:DEMO_SHOPPER_PASSWORD = "<shopper password>"
python scripts/smoke_test.py --base-url https://koushik-commerce.duckdns.org
```

It places an order and waits for it to be fulfilled while watching the live dashboard.

## Day-to-day operations

All commands run on the server, from `distributed-commerce-payments-engine/infra`. A shortcut saves typing:

```bash
alias dc='docker compose -f docker-compose.yml -f docker-compose.app.yml -f docker-compose.prod.yml'
```

| Task | Command |
|---|---|
| Deploy the latest `main` | `bash ../scripts/deploy/deploy.sh` |
| See what is running | `dc ps` |
| Follow a service's logs | `dc logs -f gateway` (any service name) |
| Restart one service | `dc restart payment-service` |
| Back up every database | `docker exec commerce-postgres pg_dumpall -U commerce \| gzip > ~/backup-$(date +%F).sql.gz` |

**Grafana and Jaeger** are deliberately not on the internet. Open a tunnel from your computer, then browse to http://localhost:13000 (Grafana, login `admin` and the Grafana password) and http://localhost:26686 (Jaeger):

```powershell
ssh -i $HOME\.ssh\oracle_commerce -L 13000:localhost:3000 -L 26686:localhost:16686 ubuntu@<public-ip>
```

The local ports differ from the usual 3000/16686 so they never clash with a stack running on your own machine.

**Never delete or regenerate `infra/.env`** on a running server: the database keeps the password it was created with, and every service would be locked out.

## Troubleshooting

| Symptom | Check |
|---|---|
| The address does not load at all | The two ingress rules from step 4; `sudo iptables -L INPUT` should list ACCEPT rules for ports 80 and 443 above the REJECT rule (re-run `setup_server.sh`) |
| Certificate or "not secure" errors | DuckDNS must point at the server's current IP; `dc logs caddy` shows why issuance failed. Caddy retries on its own once the name resolves |
| `deploy.sh` stops with an unhealthy container | `dc ps` shows which; `dc logs <service>` shows why |
| Login says the password is wrong | Demo passwords apply only when the accounts are first created; use the ones `create_env.sh` printed |

**Keeping the server:** Oracle may reclaim Always Free servers that stay almost completely idle for a week. Upgrading the account to *Pay As You Go* (Billing → Upgrade) exempts it, and resources within the Always Free limits remain free — read Oracle's current terms before you do.
