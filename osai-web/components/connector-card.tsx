import type { Integration } from "../lib/types";

export function ConnectorCard({ integration }: { integration: Integration }) {
  return (
    <article className="card">
      <h2>{integration.display_name}</h2>
      <p className="muted">Auth state: {integration.auth_state}</p>
      <div className="grid">
        <span className="badge">{integration.capabilities.join(", ")}</span>
        <span className="muted">Last sync: {integration.last_sync ?? "Never"}</span>
      </div>
    </article>
  );
}
