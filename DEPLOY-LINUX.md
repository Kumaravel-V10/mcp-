# SC-MCP-SERVER — Linux Deployment Guide

Deploy the Create Booking Agent MCP server on a Linux VM (Ubuntu/Debian).

---

## Prerequisites

| Requirement | Minimum |
|-------------|---------|
| OS | Ubuntu 22.04+ / Debian 12+ |
| Python | 3.11+ |
| RAM | 512 MB |
| Disk | 500 MB |
| Network | Outbound HTTPS to `nevioservicecenterapim.azure-api.net` |
| Ports | 3100 (or custom) inbound open |

---

## 1. Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and essentials
sudo apt install -y python3 python3-pip python3-venv git curl ufw
```

---

## 2. Deploy the MCP Server

```bash
# Create a dedicated user (security best practice)
sudo useradd -m -s /bin/bash mcpserver
sudo su - mcpserver

# Clone or copy your project
# Option A: From Git
git clone <your-repo-url> ~/sc-mcp-server
cd ~/sc-mcp-server

# Option B: SCP from local machine
# scp -r ./mcp/* mcpserver@<VM-IP>:~/sc-mcp-server/

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Configure Environment

```bash
# Copy the example and edit
cp .env.example .env
nano .env
```

**Set these values in `.env`:**

```bash
# ─── REQUIRED ───────────────────────────────────
MCP_TRANSPORT=sse
MCP_HOST=0.0.0.0
MCP_PORT=3100

# Generate a strong API key:
#   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
MCP_API_KEY=<paste-your-generated-key-here>

# ─── SAFETY ─────────────────────────────────────
# Keep false until you are ready to create real bookings
ALLOW_MUTATIONS=false

# ─── APIM ───────────────────────────────────────
APIM_BASE_URL=https://nevioservicecenterapim.azure-api.net
APIM_TOKEN_TTL=1700
API_REQUEST_TIMEOUT=30

# ─── RATE LIMITING ──────────────────────────────
RATE_LIMIT_PER_MINUTE=100

# ─── LOGGING ────────────────────────────────────
LOG_LEVEL=INFO

# ─── HTTPS (optional but recommended) ──────────
# SSL_CERTFILE=/etc/ssl/certs/mcp-server.crt
# SSL_KEYFILE=/etc/ssl/private/mcp-server.key
```

---

## 4. Verify Installation

```bash
# Activate venv
source ~/sc-mcp-server/venv/bin/activate
cd ~/sc-mcp-server

# Run readiness check — all 18 checks must pass
python3 check.py
```

Expected output:
```
=======================================================
  SC-MCP-SERVER Readiness Check (Booking Agent)
=======================================================
  ...
  ALL 18 CHECKS PASSED — Booking Agent Server is ready
=======================================================
```

---

## 5. Test Run (Manual)

```bash
# Start the server manually first to verify it works
source venv/bin/activate
python3 server.py --transport sse --host 0.0.0.0 --port 3100
```

In a separate terminal, test:

```bash
# Health check
curl http://localhost:3100/health

# List tools (with auth)
curl -H "Authorization: Bearer <your-api-key>" \
     http://localhost:3100/api/tools

# Test a tool
curl -X POST http://localhost:3100/api/tools/search_flights \
     -H "Authorization: Bearer <your-api-key>" \
     -H "Content-Type: application/json" \
     -d '{
       "trip_type": "OW",
       "departure_location": "HEL",
       "arrival_location": "LHR",
       "departure_date": "2026-08-20",
       "passengers": [{"passengerTypeCode": "ADT", "discountCode": "ADT"}]
     }'
```

Stop with `Ctrl+C` after testing.

---

## 6. Create systemd Service (Production)

This makes the MCP server start on boot, auto-restart on failure, and run as a background service.

```bash
# Switch back to your admin user
exit  # exit mcpserver user

# Create the service file
sudo nano /etc/systemd/system/sc-mcp-server.service
```

Paste this content:

```ini
[Unit]
Description=SC-MCP-SERVER — Create Booking Agent MCP Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mcpserver
Group=mcpserver
WorkingDirectory=/home/mcpserver/sc-mcp-server
EnvironmentFile=/home/mcpserver/sc-mcp-server/.env
ExecStart=/home/mcpserver/sc-mcp-server/venv/bin/python3 server.py --transport sse --host 0.0.0.0 --port 3100

# Auto-restart on failure
Restart=on-failure
RestartSec=5
StartLimitBurst=5
StartLimitIntervalSec=60

# Logging — goes to journalctl
StandardOutput=journal
StandardError=journal
SyslogIdentifier=sc-mcp-server

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/mcpserver/sc-mcp-server/logs
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable sc-mcp-server

# Start the service
sudo systemctl start sc-mcp-server

# Check status
sudo systemctl status sc-mcp-server
```

---

## 7. Firewall Configuration

```bash
# Allow the MCP server port
sudo ufw allow 3100/tcp comment "SC-MCP-SERVER"

# If using HTTPS on a different port
# sudo ufw allow 443/tcp comment "SC-MCP-SERVER HTTPS"

# Enable firewall (if not already)
sudo ufw enable
sudo ufw status
```

---

## 8. HTTPS with Nginx Reverse Proxy (Recommended)

Instead of running HTTPS directly in Python, use Nginx as a reverse proxy with Let's Encrypt SSL.

```bash
# Install Nginx and Certbot
sudo apt install -y nginx certbot python3-certbot-nginx
```

Create Nginx config:

```bash
sudo nano /etc/nginx/sites-available/sc-mcp-server
```

```nginx
server {
    listen 443 ssl http2;
    server_name mcp.yourdomain.com;

    # Let's Encrypt certificates (auto-generated by certbot)
    ssl_certificate /etc/letsencrypt/live/mcp.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.yourdomain.com/privkey.pem;

    # SSL hardening
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # SSE-specific: disable buffering for streaming
    proxy_buffering off;
    proxy_cache off;

    # Timeouts for long-running SSE connections
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;

    location / {
        proxy_pass http://127.0.0.1:3100;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name mcp.yourdomain.com;
    return 301 https://$host$request_uri;
}
```

Enable the site:

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/sc-mcp-server /etc/nginx/sites-enabled/

# Test config
sudo nginx -t

# Get SSL certificate (if using a domain)
sudo certbot --nginx -d mcp.yourdomain.com

# Restart Nginx
sudo systemctl restart nginx

# Update firewall
sudo ufw allow 'Nginx Full'
sudo ufw delete allow 3100/tcp  # close direct access
```

Now your MCP server is accessible at `https://mcp.yourdomain.com/sse`.

---

## 9. Log Management

```bash
# View live logs
sudo journalctl -u sc-mcp-server -f

# View last 100 lines
sudo journalctl -u sc-mcp-server -n 100

# View logs since today
sudo journalctl -u sc-mcp-server --since today

# View errors only
sudo journalctl -u sc-mcp-server -p err

# Log rotation is handled automatically by journald
```

---

## 10. Monitoring & Health Checks

### Automated Health Check (Cron)

```bash
sudo nano /etc/cron.d/sc-mcp-healthcheck
```

```cron
# Check MCP server health every 5 minutes, restart if down
*/5 * * * * root curl -sf http://localhost:3100/health > /dev/null || systemctl restart sc-mcp-server
```

### Uptime Check Script

```bash
sudo nano /usr/local/bin/mcp-status.sh
sudo chmod +x /usr/local/bin/mcp-status.sh
```

```bash
#!/bin/bash
echo "═══════════════════════════════════════════"
echo "  SC-MCP-SERVER Status"
echo "═══════════════════════════════════════════"
echo ""

# Service status
echo "Service:"
systemctl is-active sc-mcp-server && echo "  Status: RUNNING ✅" || echo "  Status: STOPPED ❌"
echo ""

# Health endpoint
echo "Health:"
HEALTH=$(curl -sf http://localhost:3100/health 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "  Endpoint: OK ✅"
    echo "  Response: $HEALTH" | python3 -m json.tool 2>/dev/null || echo "  $HEALTH"
else
    echo "  Endpoint: UNREACHABLE ❌"
fi
echo ""

# Port check
echo "Network:"
ss -tlnp | grep 3100 && echo "  Port 3100: LISTENING ✅" || echo "  Port 3100: NOT LISTENING ❌"
echo ""

# Memory usage
echo "Resources:"
ps aux | grep "[s]erver.py" | awk '{print "  PID: "$2"  Memory: "$6" KB  CPU: "$3"%"}'
echo ""
echo "═══════════════════════════════════════════"
```

Run with: `sudo mcp-status.sh`

---

## 11. Common Operations

```bash
# Start the server
sudo systemctl start sc-mcp-server

# Stop the server
sudo systemctl stop sc-mcp-server

# Restart (after config changes)
sudo systemctl restart sc-mcp-server

# View status
sudo systemctl status sc-mcp-server

# View live logs
sudo journalctl -u sc-mcp-server -f

# Update code (pull new version)
sudo su - mcpserver
cd ~/sc-mcp-server
git pull
source venv/bin/activate
pip install -r requirements.txt
python3 check.py
exit
sudo systemctl restart sc-mcp-server

# Enable mutations (when ready for live bookings)
sudo nano /home/mcpserver/sc-mcp-server/.env
# Change: ALLOW_MUTATIONS=true
sudo systemctl restart sc-mcp-server
```

---

## 12. Connect AI Agents to This Server

Once deployed, your agents in Azure AI Foundry connect to:

| Transport | URL |
|-----------|-----|
| **SSE (direct)** | `http://<VM-IP>:3100/sse` |
| **SSE (via Nginx)** | `https://mcp.yourdomain.com/sse` |
| **REST API** | `https://mcp.yourdomain.com/api/tools` |
| **Health** | `https://mcp.yourdomain.com/health` |

In Azure AI Foundry Agent configuration:
```
Agent → Tools → + Add Tool → MCP Server
├── MCP Server URL: https://mcp.yourdomain.com/sse
├── Authentication: API Key
├── Header Name: Authorization
├── Header Value: Bearer <your-api-key>
└── Save
```

---

## 13. Security Checklist

| # | Item | Command to Verify |
|---|------|-------------------|
| 1 | `MCP_API_KEY` is set | `grep MCP_API_KEY .env` |
| 2 | `ALLOW_MUTATIONS=false` (until ready) | `grep ALLOW_MUTATIONS .env` |
| 3 | Firewall active | `sudo ufw status` |
| 4 | Nginx HTTPS configured | `curl -I https://mcp.yourdomain.com` |
| 5 | No direct port 3100 access from internet | `sudo ufw status \| grep 3100` |
| 6 | Server runs as non-root user | `ps aux \| grep server.py` |
| 7 | Service auto-restarts on failure | `sudo systemctl show sc-mcp-server \| grep Restart` |
| 8 | Log rotation active | `sudo journalctl --disk-usage` |

---

## Quick Deploy (Copy-Paste)

For a fast deployment on a fresh Ubuntu VM:

```bash
# Run as root or with sudo
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git curl ufw

# Create user and deploy
sudo useradd -m -s /bin/bash mcpserver
sudo su - mcpserver
git clone <your-repo-url> ~/sc-mcp-server
cd ~/sc-mcp-server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Generate and set API key
API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
sed -i "s/^MCP_API_KEY=$/MCP_API_KEY=$API_KEY/" .env
sed -i "s/^MCP_TRANSPORT=stdio$/MCP_TRANSPORT=sse/" .env
sed -i "s/^MCP_HOST=127.0.0.1$/MCP_HOST=0.0.0.0/" .env

echo "Your API Key: $API_KEY"
echo "Save this key — you need it for agent configuration."

# Verify
python3 check.py
exit

# Install as service (run as admin)
# Copy the systemd unit file from step 6 above, then:
sudo systemctl daemon-reload
sudo systemctl enable --now sc-mcp-server
sudo ufw allow 3100/tcp
echo "Done! Server running at http://$(hostname -I | awk '{print $1}'):3100"
```
