// Tiny, safe markdown renderer for the AI briefing (headings, bullet lists, **bold**, _italic_).
function inline(text) {
  const parts = text.split(/(\*\*[^*]+\*\*|_[^_]+_|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("_") && p.endsWith("_") && p.length > 2) return <em key={i}>{p.slice(1, -1)}</em>;
    if (p.startsWith("`") && p.endsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
    return p;
  });
}

export default function Markdown({ text = "" }) {
  const blocks = [];
  let list = null;
  text.split("\n").forEach((raw, i) => {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*(?:[-*]|\d+\.)\s+(.*)$/);
    if (bullet) {
      if (!list) { list = []; blocks.push({ type: "ul", items: list }); }
      list.push(bullet[1]);
      return;
    }
    list = null;
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) blocks.push({ type: "h", text: h[2], key: i });
    else if (line.trim()) blocks.push({ type: "p", text: line, key: i });
  });
  return (
    <div className="md">
      {blocks.map((b, i) =>
        b.type === "ul" ? <ul key={i}>{b.items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ul>
        : b.type === "h" ? <h4 key={i}>{inline(b.text)}</h4>
        : <p key={i}>{inline(b.text)}</p>
      )}
    </div>
  );
}
