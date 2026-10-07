# Server-managed Windows connectors (pilot)

This mode moves TikTok Shop, Shopee Seller Chat, Messenger, and Instagram
connector workers from the customer PC to a Windows host. The customer ZIP
only exchanges the one-time pairing code and opens a short-lived remote login
viewer. The Windows agent keeps one Edge profile and worker per shop/channel.
Local connector mode remains the default unless the server build is selected.

## Security boundary

- Run the agent as a dedicated Windows account with access only to its connector
  data directory. Edge profiles contain login cookies and must stay on that
  host; enable BitLocker and restrict the data directory ACL.
- Set the same random secret (at least 32 characters) as
  `SERVER_CONNECTOR_AGENT_TOKEN` in `backend/.env` and the Windows agent process.
- Set `SERVER_CONNECTOR_AGENT_URL` in `backend/.env` to an address reachable
  from the backend, e.g. `http://host.docker.internal:8095` for Docker Desktop on
  the same Windows machine. Recreate backend and worker after changing it.
- Keep agent port 8095 and all Edge CDP ports private. Do not add them to an
  internet-facing reverse proxy, ngrok, or public firewall rule. For a separate
  host, use a private VPN/network and HTTPS or a TLS-protected private proxy.
- Public CRM/frontend URLs must use HTTPS, and the frontend origin must be in
  backend `CORS_ORIGINS`. Do not reuse the pilot `localhost` addresses for
  customers.
- The viewer ticket is a bearer credential, scoped to one shop/channel, stored
  hashed in the channel config, and expires after the configured TTL (default 4h).
  Pair again to issue a fresh ticket if the window expires.
- CAPTCHA, login challenges, and security prompts are handled manually by the
  shop owner in the viewer. The connector does not bypass them.

## Pilot setup on this Windows host

1. Configure `SERVER_CONNECTOR_AGENT_URL` and a fresh `SERVER_CONNECTOR_AGENT_TOKEN`
   in `backend/.env`. The run script prompts for the matching token as a secure
   PowerShell input; it is not typed into shell history. Never put it in source
   control or EXE command-line arguments.
2. Start the CRM services, then run the agent in a dedicated PowerShell window:

   ```powershell
   $env:SERVER_CONNECTOR_BACKEND_URL = "http://127.0.0.1:8000"
   $env:SERVER_CONNECTOR_AGENT_HOST = "0.0.0.0"
   .\scripts\start_server_connector_agent.ps1
   ```

   Only allow inbound 8095 from the backend's private Docker/VPN address in
   Windows Firewall. Do not expose it to the public network. Agent startup is
   intentionally manual for the first pilot. After viewer/reconnect is verified,
   an administrator can optionally run
   `scripts/install_server_connector_agent_task.ps1`; it stores the secret in a
   dedicated ProgramData folder readable only by SYSTEM/Administrators and
   registers a startup task. This installer has not been run on this machine.

3. Build the server-mode ZIP payloads using the real HTTPS API and frontend URLs:

   ```powershell
   .\scripts\build_server_connector_artifacts.ps1 -BackendUrl https://api.example.com -FrontendUrl https://crm.example.com
   ```

   Artifacts are written to `scripts/dist/*-server/`; local builds keep their
   original output directories. Once those artifacts are deployed and the
   backend agent URL/token are configured, connector ZIP downloads select the
   server build. Pair using a newly generated code in the matching shop/channel.

4. The EXE should open `server-connector-viewer.html`. Log in and resolve any
   verification prompt there. Confirm the connector heartbeat is online, then
   close the viewer and EXE. The agent remains responsible for the worker while
   it is running.

## Current pilot limits

This is a single Windows-host agent, not a multi-host scheduler. The optional
startup task should only be installed after validating the login viewer and
reconnect lifecycle.
If the agent is down, the CRM reports a connector delivery/session failure.
Deleting a shop's server-managed channel stops its worker on the next agent poll.
