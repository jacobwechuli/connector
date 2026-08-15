"use client";
import { useEffect, useState } from "react";
import { use } from "react";
import Link from "next/link";
import {
  getUpdate,
  getCommitAnalysis,
  approveUpdate,
  rejectUpdate,
  createPR,
  revertUpdate,
  getActivity,
} from "@/lib/api";
import type { PortfolioUpdate, Analysis, WorkflowEvent } from "@/lib/types";
import Badge from "@/components/Badge";
import DiffViewer from "@/components/DiffViewer";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card mt-4">
      <h2 className="font-semibold mb-3">{title}</h2>
      {children}
    </div>
  );
}

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-4 py-1.5" style={{ borderBottom: "1px solid var(--border)" }}>
      <span className="text-xs w-40 shrink-0" style={{ color: "var(--muted)" }}>{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}

export default function UpdateDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [update, setUpdate] = useState<PortfolioUpdate | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [timeline, setTimeline] = useState<WorkflowEvent[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const u = await getUpdate(Number(id));
      setUpdate(u);
      try {
        const a = await getCommitAnalysis(u.commit_id);
        setAnalysis(a);
      } catch { /* no analysis yet */ }
      try {
        // Load all activity then filter client-side by update_id and commit_id.
        const all = await getActivity(200);
        setTimeline(all.filter((e) => e.update_id === u.id || e.commit_id === u.commit_id));
      } catch { /* activity is best-effort */ }
    } catch {
      setError("Update not found.");
    }
  };

  useEffect(() => { load(); }, [id]);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError("");
    try {
      await fn();
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Action failed.");
    } finally {
      setBusy("");
    }
  };

  if (error) return (
    <div>
      <Link href="/updates" style={{ color: "var(--accent)" }}>← Updates</Link>
      <p className="mt-4" style={{ color: "#f85149" }}>{error}</p>
    </div>
  );

  if (!update) return (
    <div style={{ color: "var(--muted)" }}>Loading…</div>
  );

  const ops = update.operations?.operations ?? [];
  const events = Array.isArray(update.validation_result?.events)
    ? update.validation_result.events.map(String)
    : [];

  return (
    <div>
      <div className="mb-6">
        <Link href="/updates" className="text-sm" style={{ color: "var(--muted)" }}>
          ← All updates
        </Link>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-xl font-semibold">Update #{update.id}</h1>
          <Badge status={update.status} />
        </div>
        <p className="text-sm mt-0.5" style={{ color: "var(--muted)" }}>
          Commit #{update.commit_id}
          {update.branch && <> · branch <code className="text-xs">{update.branch}</code></>}
          {update.pr_number && <> · PR #{update.pr_number}</>}
        </p>
      </div>

      {error && (
        <p className="mb-4 text-sm rounded-lg p-2"
          style={{ background: "#1a0d0d", color: "#f85149", border: "1px solid #da363355" }}>
          {error}
        </p>
      )}

      {/* Review-first workflow callout */}
      {update.status === "pending" && (
        <div
          className="mb-4 rounded-lg p-3 text-sm"
          style={{ background: "#0d1a2a", border: "1px solid var(--accent)44", color: "var(--muted)" }}
        >
          <strong style={{ color: "var(--text)" }}>Review before committing.</strong>{" "}
          Approving marks this update as ready. You must then click{" "}
          <em>Create PR</em> to run the configured validation command and push the branch.
          No GitHub writes occur until you explicitly create the PR.
        </div>
      )}
      {update.status === "approved" && !update.pr_number && (
        <div
          className="mb-4 rounded-lg p-3 text-sm"
          style={{ background: "#0d1a0d", border: "1px solid #3fb95044", color: "var(--muted)" }}
        >
          <strong style={{ color: "var(--text)" }}>Approved — ready to publish.</strong>{" "}
          Click <em>Create PR</em> to run the configured build/test command, then create a branch and pull request.
        </div>
      )}

      {/* Action bar */}
      <div className="flex flex-wrap gap-2 mb-4">
        {update.status === "pending" && (
          <>
            <button
              disabled={!!busy}
              onClick={() => act("approve", () => approveUpdate(update.id))}
              className="btn btn-success"
            >
              {busy === "approve" ? "Approving…" : "✓ Approve"}
            </button>
            <button
              disabled={!!busy}
              onClick={() => act("reject", () => rejectUpdate(update.id))}
              className="btn btn-danger"
            >
              {busy === "reject" ? "Rejecting…" : "✗ Reject"}
            </button>
          </>
        )}
        {update.status === "approved" && !update.pr_number && (
          <button
            disabled={!!busy}
            onClick={() => act("pr", () => createPR(update.id))}
            className="btn btn-primary"
          >
            {busy === "pr" ? "Running validation & creating PR…" : "Create PR"}
          </button>
        )}
        {["pr_created", "merged", "approved"].includes(update.status) && (
          <button
            disabled={!!busy}
            onClick={() => act("revert", () => revertUpdate(update.id))}
            className="btn btn-ghost"
          >
            Revert
          </button>
        )}
      </div>

      {update.error_message && (
        <div
          className="mb-4 rounded-lg p-3 text-sm"
          style={{ background: "#1a0d0d", color: "#f85149", border: "1px solid #da363355" }}
        >
          ⚠ {update.error_message}
        </div>
      )}

      {/* Analysis summary */}
      {analysis && (
        <Section title="AI analysis">
          <KV label="Portfolio worthy" value={analysis.portfolio_worthy ? "Yes" : "No"} />
          <KV label="Significance" value={<Badge status={analysis.significance} />} />
          <KV label="Confidence" value={`${(analysis.confidence * 100).toFixed(0)}%`} />
          <KV label="Model" value={analysis.model} />
          <KV label="Prompt version" value={analysis.prompt_version} />
          <KV label="Reasoning" value={analysis.reasoning_summary} />
        </Section>
      )}

      {/* Operations */}
      <Section title={`Portfolio operations (${ops.length})`}>
        {ops.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--muted)" }}>No operations.</p>
        ) : (
          <div className="space-y-3">
            {ops.map((op, i) => (
              <div
                key={i}
                className="rounded-lg p-3 text-sm"
                style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Badge status={op.type.replace("_", " ")} />
                  {op.project_id && <code className="text-xs">{op.project_id}</code>}
                  {op.skill && <code className="text-xs">{op.skill}</code>}
                </div>
                {op.title && <p className="font-medium">{op.title}</p>}
                {op.description && <p className="mt-1" style={{ color: "var(--muted)" }}>{op.description}</p>}
                {op.changes && Object.keys(op.changes).length > 0 && (
                  <pre className="mt-2 text-xs overflow-auto" style={{ color: "var(--muted)" }}>
                    {JSON.stringify(op.changes, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Workflow timeline from DB */}
      <Section title="Workflow timeline">
        {timeline.length > 0 ? (
          <div className="space-y-0">
            {[...timeline].reverse().map((ev) => (
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
                {ev.detail && (
                  <span className="min-w-0 truncate text-xs" style={{ color: "var(--muted)" }}>
                    {ev.detail}
                  </span>
                )}
                <span className="ml-auto shrink-0 text-xs" style={{ color: "var(--muted)" }}>
                  {new Date(ev.created_at).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        ) : events.length > 0 ? (
          <ol className="list-decimal list-inside space-y-1 text-sm" style={{ color: "var(--muted)" }}>
            {events.map((event) => <li key={event}>{event.replace(/_/g, " ")}</li>)}
          </ol>
        ) : (
          <p className="text-sm" style={{ color: "var(--muted)" }}>Waiting for processing events.</p>
        )}
      </Section>

      {update.validation_result && Object.keys(update.validation_result).length > 0 && (
        <Section title="Validation">
          {Object.entries(update.validation_result).map(([k, v]) => (
            <KV key={k} label={k.replace(/_/g, " ")} value={Array.isArray(v) ? v.join(" → ") : String(v)} />
          ))}
        </Section>
      )}

      {/* Diff */}
      {update.diff && (
        <Section title="Generated diff">
          <DiffViewer diff={update.diff} />
        </Section>
      )}

      {/* Raw */}
      <details className="mt-4">
        <summary className="cursor-pointer text-xs" style={{ color: "var(--muted)" }}>
          Raw JSON
        </summary>
        <pre
          className="mt-2 text-xs overflow-auto rounded-lg p-3"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
        >
          {JSON.stringify(update, null, 2)}
        </pre>
      </details>
    </div>
  );
}
