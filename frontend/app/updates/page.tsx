"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getUpdates, approveUpdate, rejectUpdate, createPR } from "@/lib/api";
import type { PortfolioUpdate } from "@/lib/types";
import Badge from "@/components/Badge";

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

export default function UpdatesPage() {
  const [updates, setUpdates] = useState<PortfolioUpdate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      setUpdates(await getUpdates());
    } catch {
      setError("Failed to load updates.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const act = async (id: number, fn: (id: number) => Promise<unknown>) => {
    setBusy(id);
    setError("");
    try {
      await fn(id);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Action failed.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Portfolio updates</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--muted)" }}>
            AI-proposed changes awaiting review or already actioned.
          </p>
        </div>
        <button onClick={load} disabled={loading} className="btn btn-ghost">
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      {error && (
        <p className="mb-4 text-sm rounded-lg p-2"
          style={{ background: "#1a0d0d", color: "#f85149", border: "1px solid #da363355" }}>
          {error}
        </p>
      )}

      {updates.length === 0 && !loading ? (
        <div className="card text-center py-12" style={{ color: "var(--muted)" }}>
          <p className="text-2xl mb-2">📭</p>
          <p>No portfolio updates yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {updates.map((u) => {
            const ops = u.operations?.operations ?? [];
            const isBusy = busy === u.id;
            return (
              <div key={u.id} className="card">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Link href={`/updates/${u.id}`} className="font-medium hover:underline">
                        Update #{u.id}
                      </Link>
                      <Badge status={u.status} />
                    </div>
                    <p className="text-xs" style={{ color: "var(--muted)" }}>
                      {ops.length} operation(s) · {timeAgo(u.created_at)}
                      {u.branch && <> · <code>{u.branch}</code></>}
                      {u.pr_number && <> · PR #{u.pr_number}</>}
                    </p>
                    {ops.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {ops.map((op, i) => (
                          <span
                            key={i}
                            className="badge badge-minor"
                          >
                            {op.type}{op.skill ? `: ${op.skill}` : ""}
                            {op.project_id ? ` → ${op.project_id}` : ""}
                          </span>
                        ))}
                      </div>
                    )}
                    {u.error_message && (
                      <p className="mt-2 text-xs rounded p-1"
                        style={{ background: "#1a0d0d", color: "#f85149" }}>
                        ⚠ {u.error_message.slice(0, 120)}
                      </p>
                    )}
                  </div>

                  {/* Action buttons */}
                  <div className="flex flex-col gap-1.5 shrink-0">
                    <Link href={`/updates/${u.id}`} className="btn btn-ghost" style={{ textAlign: "center" }}>
                      Details →
                    </Link>
                    {u.status === "pending" && (
                      <>
                        <button
                          disabled={isBusy}
                          onClick={() => act(u.id, approveUpdate)}
                          className="btn btn-success"
                        >
                          ✓ Approve
                        </button>
                        <button
                          disabled={isBusy}
                          onClick={() => act(u.id, rejectUpdate)}
                          className="btn btn-danger"
                        >
                          ✗ Reject
                        </button>
                      </>
                    )}
                    {u.status === "approved" && !u.pr_number && (
                      <button
                        disabled={isBusy}
                        onClick={() => act(u.id, createPR)}
                        className="btn btn-primary"
                      >
                        {isBusy ? "Creating…" : "Create PR"}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
