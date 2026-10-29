# Deploy FabAgent on a Nebius VM

The app is a long-lived Streamlit process. It needs outbound HTTPS for Nebius
Token Factory and Tavily, and **server-side** keys. The browser never receives a
key.

## 1. Server environment

Create `/etc/fabagent.env` (root-readable only) with the two keys:

```sh
sudo install -m 600 /dev/null /etc/fabagent.env
sudo editor /etc/fabagent.env
```

```sh
NEBIUS_API_KEY=...
TAVILY_API_KEY=...
```

Do not commit this file, paste it into a screenshot, or put it in the browser.
The app reads it through the process environment (or a local `.env` for
development).

## 2. Docker (recommended for a repeatable demo)

From the repository root:

```sh
docker build -t fabagent .
docker run -d --name fabagent --restart unless-stopped \
  --env-file /etc/fabagent.env \
  -p 8501:8501 \
  fabagent
```

Check the health endpoint:

```sh
curl -fsS http://127.0.0.1:8501/_stcore/health
```

Then expose port 8501 through the Nebius firewall or reverse proxy. For a quick
demo, the VM public IP plus `:8501` is enough. Do not expose any other port.

### Simplest public URL (no domain needed)

The hackathon accepts a hosted application URL; it does **not** require a custom
domain. The cheapest path is:

1. Give the VM a public IP in the Nebius console.
2. Add an inbound security-group/firewall rule for **TCP 8501** from the
   internet (demo only), and keep SSH 22 restricted to your own IP.
3. Open `http://<public-ip>:8501` in an incognito window.

That URL is enough for Devpost. It is HTTP, not HTTPS; for a short-lived
hackathon demo that is acceptable. Do not spend time buying a domain unless you
specifically need a stable name or TLS.

If you want HTTPS without buying a domain, run a Cloudflare quick tunnel on the
VM:

```sh
cloudflared tunnel --url http://127.0.0.1:8501
```

It prints a temporary `https://…trycloudflare.com` URL. Keep `cloudflared`
running (systemd is safer than a terminal). The app still runs on the Nebius VM;
the tunnel only exposes it. A quick-tunnel URL changes if the process restarts,
so paste the final URL into `docs/ui/contact.md` and the README just before
submission.

A free `nip.io` name also works without a domain:
`http://203-0-113-10.nip.io:8501` (replace the dots in the public IP with
hyphens).

## 3. Tool models are read-only in the hosted UI

The “unknown export → draft YAML” flow never writes a shared config. The user can
download the draft and paste it back as an advanced tool model on a later run;
persisting a new default model is a deliberate repository/deployment step. This
keeps the multi-user hosted demo stateless and prevents one visitor from changing
the tool model for everyone else.

No config-directory volume mount is required.

## 4. systemd (no Docker)

```ini
[Unit]
Description=FabAgent Streamlit
After=network-online.target
Wants=network-online.target

[Service]
User=fabagent
WorkingDirectory=/opt/fabagent
EnvironmentFile=/etc/fabagent.env
ExecStart=/opt/fabagent/.venv/bin/streamlit run src/ui/app.py \
  --server.address=0.0.0.0 \
  --server.port=8501 \
  --server.headless=true \
  --browser.gatherUsageStats=false
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now fabagent
sudo systemctl status fabagent
```

## 5. Pre-video checklist

1. Restart the process after any code change (`Ctrl+C`, then start again). The
   app has a stale-loader guard, but a restart is the clean path.
2. Open the hosted URL in an **incognito** window.
3. Confirm the sidebar says **NVIDIA Nemotron: Live** and **Tavily research:
   Live**.
4. Run the TEP feed case: **Fault Confirmed**, with a live Nemotron explanation.
5. Run the RF sensor-conflict case: **Sensors Disagree**, and open **Tavily
   research** to show real public leads.
6. Run the unknown-tool case; download the draft YAML. Do not promise that the
   hosted UI saves it — it is stateless by design. Use the downloaded file in
   Engineer settings on a later run if you want to demonstrate the promotion
   path.
7. Do not show `.env`, `/etc/fabagent.env`, the terminal history, or raw model
   completions.
8. Keep `NEBIUS_API_KEY` and `TAVILY_API_KEY` server-side. If you rotate a key,
   restart the service.
