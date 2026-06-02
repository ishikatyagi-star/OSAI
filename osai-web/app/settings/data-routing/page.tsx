export default function DataRoutingPage() {
  return (
    <>
      <header className="page-header">
        <h1>Data Routing</h1>
        <p>Configure Normal, Amber, and Red tier handling before retrieval or model calls.</p>
      </header>
      <section className="grid cols">
        {[
          ["Normal", "Cloud model route allowed with audit logging."],
          ["Amber", "Cloud route allowed after stricter prompt and citation checks."],
          ["Red", "Local-only route until explicitly enabled."]
        ].map(([tier, description]) => (
          <article className="card" key={tier}>
            <h2>{tier}</h2>
            <p className="muted">{description}</p>
          </article>
        ))}
      </section>
    </>
  );
}
