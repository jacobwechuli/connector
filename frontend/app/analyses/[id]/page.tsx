"use client";
import { useEffect, useState } from "react";
import { use } from "react";
import Link from "next/link";
import { getAnalyses } from "@/lib/api";
import type { Analysis } from "@/lib/types";
import Badge from "@/components/Badge";

export default function AnalysisDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const all = await getAnalyses();
        const a = all.find((x) => x.id === Number(id));
        if (!a) throw new Error("Not found");
        setAnalysis(a);
      } catch {
        setError("Analysis not found.");
      }
    })();
  }, [id]);

  if (error) return (
    <div>
      <Link href="/analyses" style={{ color: "var(--accent)" }}>← Analyses</Link>
      <p className="mt-4" style={{ color: "#f85149" }}>{error}</p>
    </div>
  );

  if (!analysis) return <p style={{ color: "var(--muted)" }}>Loading…</p>;

  const raw = analysis.raw_result;

  function KV({ label, value }: { label: string; value: React.ReactNode }) {
    return (
      <div className="flex gap-4 py-1.5" style={{ borderBottom: "1px solid var(--border)" }}>
        <span className="text-xs w-40 shrink-0" style={{ color: "var(--muted)" }}>{label}</span>
        <span className="text-sm">{value}</span>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <Link href="/analyses" className="text-sm" style={{ color: "var(--muted)" }}>
          ← All analyses
        </Link>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-xl font-semibold">Analysis #{analysis.id}</h1>
          <Badge status={analysis.significance} />
        </div>
      </div>

      <div className="card">
        <KV label="Commit" value={<Link href={`/analyses?commit_id=${analysis.commit_id}`} style={{ color: "var(--accent)" }}>#{analysis.commit_id}</Link>} />
        <KV label="Portfolio worthy" value={analysis.portfolio_worthy ? "Yes ✓" : "No"} />
        <KV label="Significance" value={<Badge status={analysis.significance} />} />
        <KV label="Confidence" value={`${(analysis.confidence * 100).toFixed(0)}%`} />
        <KV label="Category" value={String(raw.category ?? "–")} />
        <KV label="Model" value={analysis.model} />
        <KV label="Prompt version" value={analysis.prompt_version} />
        <KV label="Created" value={new Date(analysis.created_at).toLocaleString()} />
      </div>

      <div className="card mt-4">
        <h2 className="font-semibold mb-2">Why this matters</h2>
        <p className="text-sm">{analysis.reasoning_summary}</p>
      </div>

      {(raw.technologies as string[] | undefined)?.length ? (
        <div className="card mt-4">
          <h2 className="font-semibold mb-2">Technologies detected</h2>
          <div className="flex flex-wrap gap-2">
            {(raw.technologies as string[]).map((t) => (
              <Badge key={t} status={t} />
            ))}
          </div>
        </div>
      ) : null}

      {(raw.new_capabilities as string[] | undefined)?.length ? (
        <div className="card mt-4">
          <h2 className="font-semibold mb-2">New capabilities</h2>
          <ul className="list-disc list-inside text-sm space-y-1" style={{ color: "var(--muted)" }}>
            {(raw.new_capabilities as string[]).map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <details className="mt-4">
        <summary className="cursor-pointer text-xs" style={{ color: "var(--muted)" }}>
          Raw AI output
        </summary>
        <pre
          className="mt-2 text-xs overflow-auto rounded-lg p-3"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
        >
          {JSON.stringify(raw, null, 2)}
        </pre>
      </details>
    </div>
  );
}
