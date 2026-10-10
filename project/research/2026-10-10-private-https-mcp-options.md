# Private HTTPS options for Ariadne MCP

Status: research, not an approved deployment design. No infrastructure was changed.

## Existing constraints

Issue #18 and specification 0005 require a private HTTPS endpoint, the existing loopback-only Ariadne HTTP service, application bearer enforcement on every request, and actual remote acceptance. Public exposure, OAuth and multi-project service are outside the approved scope.

## Options

| Option | Appropriate use | Main prerequisite / limitation |
| --- | --- | --- |
| Tailscale Serve | Local or server-side MCP clients in the tailnet | Enable tailnet HTTPS, authorize clients through access rules; hostname is under the tailnet's `ts.net` domain. Cloud-hosted clients need their own route into the tailnet. |
| Caddy, nginx or Traefik on a private network / VPN | Own hostname or existing private ingress | Configure private reachability, certificates and renewal. Caddy can automate HTTPS; an internal CA requires client trust, while DNS-01 can obtain a public certificate without exposing the service's HTTP ports. |
| Existing organizational HTTPS ingress | Managed server environment | Reuse its private routing and certificate management; verify MCP streaming, headers and bearer forwarding. |
| Cloudflare Tunnel with a separately selected access policy | Outbound-only origin connectivity | Tunnel alone is not caller authorization. A published hostname with Access differs from a private-network endpoint; private routing requires the corresponding client connectivity. Additional auth must work with the actual MCP client. Cloudflare becomes part of the traffic path. Not selected for #18. |

Recommendation, not owner decision: Tailscale Serve is the smallest option if every intended MCP client can reach the tailnet. Otherwise determine whether the caller is a local agent process or a cloud-hosted connector before choosing ingress. Public-only connectors cannot directly use a tailnet endpoint; public exposure would require a scope decision.

The proxy must preserve Authorization and MCP session/protocol headers and support streaming without destructive buffering or timeouts. TLS does not replace Ariadne's bearer gate. Caddy documents immediate flushing for `text/event-stream`; other proxy configurations must be checked rather than assumed equivalent.

## Sources

Official documentation consulted on 2026-10-10:

- Tailscale Serve: https://tailscale.com/kb/1312/serve — private tailnet proxy, HTTPS prerequisites, access controls and hostname limitations; Funnel is the public alternative, not selected here.
- Caddy automatic HTTPS: https://caddyserver.com/docs/automatic-https — certificate renewal, local CA trust and DNS challenge options.
- Caddy reverse proxy: https://caddyserver.com/docs/caddyfile/directives/reverse_proxy — streaming and buffering behavior.
- Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/ — outbound-only origin connectivity and distinction from public application publishing.
- MCP transport specification, version 2025-06-18: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports — Streamable HTTP, SSE and session/protocol headers. Versioned reference, not a claim about the latest specification.
- Repository source: project/specs/2026-09-24-0005-harness-led-authoring.md and https://github.com/legout/ariadne/issues/18.

No live proxy, certificate, client, source-access or deployment acceptance checks were run. The research note is local and uncommitted.
