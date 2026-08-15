"use client";

interface Props {
  diff: string;
  maxLines?: number;
}

export default function DiffViewer({ diff, maxLines = 300 }: Props) {
  const lines = diff.split("\n").slice(0, maxLines);
  const truncated = diff.split("\n").length > maxLines;

  return (
    <div className="diff-block">
      {lines.map((line, i) => {
        let cls = "";
        if (line.startsWith("+") && !line.startsWith("+++")) cls = "diff-add";
        else if (line.startsWith("-") && !line.startsWith("---")) cls = "diff-del";
        else if (line.startsWith("@@")) cls = "diff-meta";
        return (
          <span key={i} className={cls}>
            {line}
            {"\n"}
          </span>
        );
      })}
      {truncated && (
        <span style={{ color: "var(--muted)" }}>
          … diff truncated at {maxLines} lines
        </span>
      )}
    </div>
  );
}
