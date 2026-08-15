"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getRepositories, getUpdates, getAnalyses, getActivity } from "@/lib/api";
import type { Repository, PortfolioUpdate, Analysis, WorkflowEvent } from "@/lib/types";
import Badge from "@/components/Badge";

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="card">
      <p className="label">{label}</p>
      <p className="mt-1 text-3xl font-semibold">{value}</p>
      {sub && <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>{sub}</p>}
    </div>
  );
}

function timeAgo(iso: string | null) {
  if (!iso) return "–";
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function OverviewPage() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [updates, setUpdates] = useState<PortfolioUpdate[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [activity, setActivity] = useState<WorkflowEvent[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setError("");
    const [repositoryResult, updateResult, analysisResult, activityResult] = await Promise.allSettled([
      getRepositories(), getUpdates(), getAnalyses(), getActivity(30),
    ]);
    const failures: string[] = [];
    if (repositoryResult.status === "fulfilled") setRepos(repositoryResult.value);
    else failures.push(`repositories: ${repositoryResult.reason instanceof Error ? repositoryResult.reason.message : "request failed"}`);
    if (updateResult.status === "fulfilled") setUpdates(updateResult.value);
    else failures.push(`updates: ${updateResult.reason instanceof Error ? updateResult.reason.message : "request failed"}`);
    if (analysisResult.status === "fulfilled") setAnalyses(analysisResult.value);
    else failures.push(`analyses: ${analysisResult.reason instanceof Error ? analysisResult.reason.message : "request failed"}`);
    if (activityResult.status === "fulfilled") setActivity(activityResult.value);
    // Activity is best-effort; don't surface its failure as a top-level error.
    if (failures.length) {
      setError(`Some dashboard data could not load — ${failures.join("; ")}`);
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const pending = updates.filter((u) => u.status === "pending").length;
  const prs = updates.filter((u) => u.pr_number).length;
  const recentActivity = [...updates]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 8);

  return (
    <div>
      {/* Header */}
      <div className="mb-8 flex items-start justify-between">
        <div>
          <p className="label">GitHub → intelligence → portfolio</p>
          <h1 className="mt-1 text-2xl font-semibold">AI Portfolio Maintainer</h1>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            Reviewable, evidence-based portfolio synchronization.
          </p>
        </div>
        <button onClick={load} disabled={loading} className="btn btn-ghost">
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      {error && (
        <div
          className="mb-6 rounded-lg p-3 text-sm"
          style={{
            background: "#1a0d0d",
            border: "1px solid #da363355",
            color: "#f85149",
          }}
        >
          {error}
        </div>
      )}

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-8">
        <StatCard label="Connected repositories" value={repos.length} />
        <StatCard label="Commits analyzed" value={analyses.length} />
        <StatCard label="Portfolio updates" value={updates.length} sub={`${prs} PRs created`} />
        <StatCard
          label="Pending approval"
          value={pending}
          sub={pending > 0 ? "Action required" : "All clear"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Repositories */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Repositories</h2>
            <Link href="/repositories" className="text-xs" style={{ color: "var(--accent)" }}>
              Manage →
            </Link>
          </div>
          {repos.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--muted)" }}>
              No repositories connected yet.{" "}
              <Link href="/repositories" style={{ color: "var(--accent)" }}>
                Add one →
              </Link>
            </p>
          ) : (
            <div className="space-y-3">
              {repos.slice(0, 6).map((r) => (
                <div
                  key={r.id}
                  className="flex items-center justify-between py-2"
                  style={{ borderBottom: "1px solid var(--border)" }}
                >
                  <div>
                    <p className="text-sm font-medium">
                      {r.owner}/{r.name}
                    </p>
                    <p className="text-xs" style={{ color: "var(--muted)" }}>
                      {r.portfolio_project_id ? `→ ${r.portfolio_project_id}` : "Not mapped"}
                      {r.is_portfolio ? " · portfolio repo" : ""}
                    </p>
                  </div>
                  <Badge status={r.enabled ? "analyzed" : "failed"} />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent portfolio updates */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Recent updates</h2>
            <Link href="/updates" className="text-xs" style={{ color: "var(--accent)" }}>
              All updates →
            </Link>
          </div>
          {recentActivity.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--muted)" }}>
              No portfolio updates yet.
            </p>
          ) : (
            <div className="space-y-3">
              {recentActivity.map((u) => (
                <div
                  key={u.id}
                  className="flex items-start justify-between py-2"
                  style={{ borderBottom: "1px solid var(--border)" }}
                >
                  <div className="min-w-0 mr-3">
                    <Link
                      href={`/updates/${u.id}`}
                      className="text-sm font-medium hover:underline"
                    >
                      Update #{u.id}
                    </Link>
                    <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
                      {u.operations?.operations?.length ?? 0} operation(s) ·{" "}
                      {timeAgo(u.created_at)}
                      {u.pr_number && ` · PR #${u.pr_number}`}
                    </p>
                  </div>
                  <Badge status={u.status} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Activity feed */}
      {activity.length > 0 && (
        <div className="card mt-6">
          <h2 className="font-semibold mb-3">Activity feed</h2>
          <div className="space-y-0">
            {activity.map((ev) => (
              <div
                key={ev.id}
                className="flex items-start gap-3 py-2 text-sm"
                style={{ borderBottom: "1px solid var(--border)" }}
              >
                <span
                  className="shrink-0 rounded px-1.5 py-0.5 text-xs font-mono"
                  style={{ background: "var(--surface-2)", color: "var(--accent)" }}
                >
                  {ev.stage.replace(/_/g, " ")}
                </span>
                <span className="min-w-0 truncate" style={{ color: "var(--muted)" }}>
                  {ev.detail ?? ""}
                  {ev.update_id && (
                    <Link
                      href={`/updates/${ev.update_id}`}
                      className="ml-2"
                      style={{ color: "var(--accent)" }}
                    >
                      update #{ev.update_id}
                    </Link>
                  )}
                </span>
                <span className="ml-auto shrink-0 text-xs" style={{ color: "var(--muted)" }}>
                  {timeAgo(ev.created_at)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* First-run callout */}
      {!loading && repos.length === 0 && (
        <div
          className="mt-8 card"
          style={{ borderColor: "var(--accent)55", background: "#0d1826" }}
        >
          <h2 className="font-semibold mb-3">Getting started</h2>
          <ol
            className="list-decimal list-inside space-y-2 text-sm"
            style={{ color: "var(--muted)" }}
          >
            <li>
              Set <code className="text-xs">GITHUB_TOKEN</code> or GitHub App credentials in{" "}
              <code className="text-xs">.env</code>
            </li>
            <li>
              Set <code className="text-xs">PORTFOLIO_OWNER</code> and{" "}
              <code className="text-xs">PORTFOLIO_REPO</code>
            </li>
            <li>
              Configure <code className="text-xs">OPENAI_API_KEY</code> or Groq
            </li>
            <li>
              <Link href="/repositories" style={{ color: "var(--accent)" }}>
                Connect a repository →
              </Link>
            </li>
            <li>Push a commit and watch the dashboard update</li>
          </ol>
        </div>
      )}
    </div>
  );
}
