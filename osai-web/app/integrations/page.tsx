import { ConnectorCard } from "../../components/connector-card";
import { getIntegrations } from "../../lib/api";

export default async function IntegrationsPage() {
  const integrations = await getIntegrations();

  return (
    <>
      <header className="page-header">
        <h1>Integrations</h1>
        <p>Connector status, scopes, last sync, and configuration state for the pilot stack.</p>
      </header>
      <section className="grid cols">
        {integrations.map((integration) => (
          <ConnectorCard key={integration.key} integration={integration} />
        ))}
        {integrations.length === 0 ? <p className="muted">API not connected yet.</p> : null}
      </section>
    </>
  );
}
