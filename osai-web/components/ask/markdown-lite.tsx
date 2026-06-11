import * as React from "react";

/**
 * Minimal, safe markdown renderer for agent answers. Supports **bold**, line
 * breaks, and simple ordered/unordered lists. Avoids dangerouslySetInnerHTML —
 * everything is rendered as React nodes.
 */

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  // Split on **bold** segments.
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    const m = part.match(/^\*\*([^*]+)\*\*$/);
    if (m) {
      return (
        <strong key={`${keyPrefix}-b-${i}`} className="font-semibold text-foreground">
          {m[1]}
        </strong>
      );
    }
    return <React.Fragment key={`${keyPrefix}-t-${i}`}>{part}</React.Fragment>;
  });
}

export function MarkdownLite({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: React.ReactNode[] = [];
  let listBuffer: { ordered: boolean; items: string[] } | null = null;

  const flushList = (key: string) => {
    if (!listBuffer) return;
    const { ordered, items } = listBuffer;
    const ListTag = ordered ? "ol" : "ul";
    blocks.push(
      <ListTag
        key={key}
        className={ordered ? "ml-5 list-decimal space-y-1.5 my-2" : "ml-5 list-disc space-y-1.5 my-2"}
      >
        {items.map((item, i) => (
          <li key={`${key}-li-${i}`}>{renderInline(item, `${key}-li-${i}`)}</li>
        ))}
      </ListTag>
    );
    listBuffer = null;
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();
    const ordered = /^\d+\.\s+/.test(trimmed);
    const unordered = /^[-*]\s+/.test(trimmed);

    if (ordered || unordered) {
      const content = trimmed.replace(/^(\d+\.|[-*])\s+/, "");
      if (!listBuffer || listBuffer.ordered !== ordered) {
        flushList(`list-${idx}`);
        listBuffer = { ordered, items: [] };
      }
      listBuffer.items.push(content);
      return;
    }

    flushList(`list-${idx}`);

    if (trimmed === "") {
      return;
    }
    blocks.push(
      <p key={`p-${idx}`} className="leading-relaxed">
        {renderInline(trimmed, `p-${idx}`)}
      </p>
    );
  });

  flushList("list-final");

  return <div className="space-y-2 text-sm text-foreground/90">{blocks}</div>;
}
