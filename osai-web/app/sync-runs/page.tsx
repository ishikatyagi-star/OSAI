import { getSyncRuns } from "../../lib/api";

export default async function SyncRunsPage() {
  const syncRuns = await getSyncRuns();

  return (
    <>
      <header className="page-header">
        <h1>Sync Runs</h1>
        <p>Recent ingestion jobs, indexed document counts, and visible failure state.</p>
      </header>
      <table className="table">
        <thead>
          <tr>
            <th>Connector</th>
            <th>Status</th>
            <th>Started</th>
            <th>Indexed</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {syncRuns.map((run) => (
            <tr key={run.id}>
              <td>{run.connector_key}</td>
              <td>{run.status}</td>
              <td>{new Date(run.started_at).toLocaleString()}</td>
              <td>{run.documents_indexed}</td>
              <td>{run.error ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
