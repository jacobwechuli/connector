"use client";
import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { getAnalyses, getCommitAnalysis } from "@/lib/api";
import type { Analysis } from "@/lib/types";
import Badge from "@/components/Badge";

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function AnalysesInner() {
  const params = useSearchParams();
  const commitFilter = params.get("commit_id");

  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        if (commitFilter) {
          const a = await getCommitAnalysis(Number(commitFilter));
          setAnalyses([a]);
        } else {
          setAnalyses(await getAnalyses());
        }
      } catch { /* ignore */ }
      setLoading(false);
    })();
  }, [commitFilter]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            {commitFilter ? `Analysis for commit #${commitFilter}` : "Analyses"}
          </h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--muted)" }}>
            {commitFilter ? (
              <Link href="/analyses" style={{ color: "var(--accent)" }}>← All analyses</Link>
            ) : (
              "AI significance classifications for analyzed commits."
            )}
          </p>
        </div>
      </div>

      {loading ? (
        <p style={{ color: "var(--muted)" }}>Loading…</p>
      ) : analyses.length === 0 ? (
        <div className="card text-center py-12" style={{ color: "var(--muted)" }}>
          <p className="text-2xl mb-2">🔬</p>
          <p>No analyses yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {analyses.map((a) => (
            <div key={a.id} className="card">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge status={a.significance} />
                    <Badge status={a.portfolio_worthy ? "analyzed" : "failed"} />
                    <span className="text-xs" style={{ color: "var(--muted)" }}>
                      {(a.confidence * 100).toFixed(0)}% confidence
                    </span>
                  </div>
                  <p className="text-sm mt-1">{a.reasoning_summary}</p>
                  <p className="text-xs mt-1.5" style={{ color: "var(--muted)" }}>
                    Commit #{a.commit_id} · {a.model} · {a.prompt_version} · {timeAgo(a.created_at)}
                  </p>
                  {/* Technologies detected */}
                  {(a.raw_result?.technologies as string[] | undefined)?.length ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {(a.raw_result.technologies as string[]).map((t) => (
                        <span key={t} className="badge badge-minor">{t}</span>
                      ))}
                    </div>
                  ) : null}
                </div>
                <Link
                  href={`/analyses/${a.id}`}
                  className="btn btn-ghost shrink-0"
                  style={{ fontSize: "0.75rem" }}
                >
                  Details →
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AnalysesPage() {
  return (
    <Suspense fallback={<p style={{ color: "var(--muted)" }}>Loading…</p>}>
      <AnalysesInner />
    </Suspense>
  );
}
