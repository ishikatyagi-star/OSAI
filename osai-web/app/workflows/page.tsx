import Link from "next/link";
import { WorkflowStatus } from "../../components/workflow-status";
import { getWorkflowRuns } from "../../lib/api";

export default async function WorkflowsPage() {
  const workflows = await getWorkflowRuns();

  return (
    <>
      <header className="page-header">
        <h1>Workflows</h1>
        <p>Meeting notes to action items, tasks, tickets, summaries, and audit trail.</p>
      </header>
      <section className="card">
        <h2>Run action extraction</h2>
        <textarea className="text-area" placeholder="Paste meeting notes or transcript..." />
        <div style={{ marginTop: 12 }}>
          <button className="button" type="button">
            Extract Actions
          </button>
        </div>
      </section>
      <table className="table" style={{ marginTop: 16 }}>
        <thead>
          <tr>
            <th>Run</th>
            <th>Status</th>
            <th>Model</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {workflows.map((workflow) => (
            <tr key={workflow.id}>
              <td>
                <Link href={`/workflows/${workflow.id}`}>{workflow.id}</Link>
              </td>
              <td>
                <WorkflowStatus status={workflow.status} />
              </td>
              <td>{workflow.model}</td>
              <td>{workflow.actions_created}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
