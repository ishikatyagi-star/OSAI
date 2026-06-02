export function SourceCitation({
  title,
  tool,
  confidence
}: {
  title: string;
  tool: string;
  confidence: number;
}) {
  return (
    <div className="card">
      <strong>{title}</strong>
      <p className="muted">
        {tool} citation, confidence {Math.round(confidence * 100)}%
      </p>
    </div>
  );
}
