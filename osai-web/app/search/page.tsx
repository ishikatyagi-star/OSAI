import { SourceCitation } from "../../components/source-citation";

export default function SearchPage() {
  return (
    <>
      <header className="page-header">
        <h1>Search</h1>
        <p>Ask across connected company context. Confident answers require citations.</p>
      </header>
      <section className="grid">
        <form className="card">
          <input className="search-box" placeholder="Search company context..." name="query" />
          <div style={{ marginTop: 12 }}>
            <button className="button" type="button">
              Search
            </button>
          </div>
        </form>
        <div className="card">
          <h2>Answer</h2>
          <p className="muted">I do not have enough connected context yet.</p>
        </div>
        <SourceCitation title="No source selected" tool="OSAI" confidence={0} />
      </section>
    </>
  );
}
