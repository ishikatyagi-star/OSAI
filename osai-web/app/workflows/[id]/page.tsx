import { WorkflowStatus } from "../../../components/workflow-status";

export default async function WorkflowDetailPage({
  params
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return (
    <>
      <header className="page-header">
        <h1>Workflow {id}</h1>
        <p>Extracted items, downstream actions, model route, failures, and audit events.</p>
      </header>
      <section className="grid cols">
        <article className="card">
          <h2>Status</h2>
          <WorkflowStatus status="ready" />
        </article>
        <article className="card">
          <h2>Extracted Items</h2>
          <p className="muted">No workflow output recorded yet.</p>
        </article>
        <article className="card">
          <h2>External Actions</h2>
          <p className="muted">No downstream writes attempted yet.</p>
        </article>
      </section>
    </>
  );
}
