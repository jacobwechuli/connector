"use client";
import { useEffect, useState } from "react";
import {
  getRepositories,
  addRepository,
  updateRepository,
  deleteRepository,
  getRepositoryCommits,
  analyzeCommit,
} from "@/lib/api";
import type { Repository, Commit } from "@/lib/types";
import Badge from "@/components/Badge";
import Link from "next/link";

type FormData = {
  owner: string;
  name: string;
  portfolio_project_id: string;
  enabled: boolean;
  auto_create_pr: boolean;
  auto_merge: boolean;
  is_portfolio: boolean;
};

const EMPTY: FormData = {
  owner: "",
  name: "",
  portfolio_project_id: "",
  enabled: true,
  auto_create_pr: true,
  auto_merge: false,
  is_portfolio: false,
};

export default function RepositoriesPage() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [editing, setEditing] = useState<Repository | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormData>(EMPTY);
  const [commits, setCommits] = useState<Record<number, Commit[]>>({});
  const [expanded, setExpanded] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      setRepos(await getRepositories());
    } catch {
      setError("Could not load repositories.");
    }
  };

  useEffect(() => { load(); }, []);

  const openAdd = () => {
    setEditing(null);
    setForm(EMPTY);
    setShowForm(true);
  };

  const openEdit = (r: Repository) => {
    setEditing(r);
    setForm({
      owner: r.owner,
      name: r.name,
      portfolio_project_id: r.portfolio_project_id ?? "",
      enabled: r.enabled,
      auto_create_pr: r.auto_create_pr,
      auto_merge: r.auto_merge,
      is_portfolio: r.is_portfolio,
    });
    setShowForm(true);
  };

  const save = async () => {
    if (!form.owner || !form.name) { setError("Owner and name are required."); return; }
    setSaving(true);
    setError("");
    try {
      const body = { ...form, portfolio_project_id: form.portfolio_project_id || null };
      if (editing) {
        await updateRepository(editing.id, body);
      } else {
        await addRepository(body);
      }
      setShowForm(false);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Disconnect this repository? This does not affect GitHub.")) return;
    await deleteRepository(id);
    await load();
  };

  const toggleExpand = async (r: Repository) => {
    if (expanded === r.id) { setExpanded(null); return; }
    setExpanded(r.id);
    if (!commits[r.id]) {
      try {
        const c = await getRepositoryCommits(r.id);
        setCommits((prev) => ({ ...prev, [r.id]: c }));
      } catch { /* ignore */ }
    }
  };

  const triggerAnalysis = async (commitId: number, repoId: number) => {
    await analyzeCommit(commitId);
    const c = await getRepositoryCommits(repoId);
    setCommits((prev) => ({ ...prev, [repoId]: c }));
  };

  const field = (key: keyof FormData) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [key]: value }));
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Repositories</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--muted)" }}>
            Manage which GitHub repositories are monitored.
          </p>
        </div>
        <button onClick={openAdd} className="btn btn-primary">+ Connect repository</button>
      </div>

      {error && (
        <p className="mb-4 text-sm rounded-lg p-2"
          style={{ background: "#1a0d0d", color: "#f85149", border: "1px solid #da363355" }}>
          {error}
        </p>
      )}

      {/* Add/edit form */}
      {showForm && (
        <div className="card mb-6" style={{ borderColor: "var(--accent)55" }}>
          <h2 className="font-semibold mb-4">{editing ? "Edit repository" : "Connect repository"}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="field">
              <label>GitHub owner</label>
              <input className="input" placeholder="octocat" value={form.owner} onChange={field("owner")} />
            </div>
            <div className="field">
              <label>Repository name</label>
              <input className="input" placeholder="my-project" value={form.name} onChange={field("name")} />
            </div>
            <div className="field sm:col-span-2">
              <label>Portfolio project ID (slug)</label>
              <input
                className="input"
                placeholder="my-project  (leave blank if unrelated to portfolio)"
                value={form.portfolio_project_id}
                onChange={field("portfolio_project_id")}
              />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            {(
              [
                ["enabled", "Monitor commits"],
                ["auto_create_pr", "Auto-create PRs"],
                ["auto_merge", "Auto-merge (caution)"],
                ["is_portfolio", "This IS the portfolio repo"],
              ] as [keyof FormData, string][]
            ).map(([key, label]) => (
              <label key={key} className="flex items-center gap-2 cursor-pointer" style={{ color: "var(--text)" }}>
                <input
                  type="checkbox"
                  checked={form[key] as boolean}
                  onChange={field(key)}
                  className="accent-blue-500"
                />
                {label}
              </label>
            ))}
          </div>
          <div className="mt-4 flex gap-2">
            <button onClick={save} disabled={saving} className="btn btn-primary">
              {saving ? "Saving…" : editing ? "Save changes" : "Connect"}
            </button>
            <button onClick={() => setShowForm(false)} className="btn btn-ghost">Cancel</button>
          </div>
        </div>
      )}

      {/* Repository list */}
      {repos.length === 0 ? (
        <div className="card text-center py-12" style={{ color: "var(--muted)" }}>
          <p className="text-2xl mb-2">🔌</p>
          <p>No repositories connected.</p>
          <button onClick={openAdd} className="btn btn-primary mt-4">Connect your first repository</button>
        </div>
      ) : (
        <div className="space-y-3">
          {repos.map((r) => (
            <div key={r.id} className="card">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">
                      {r.owner}/{r.name}
                    </span>
                    <Badge status={r.enabled ? "analyzed" : "failed"} />
                    {r.is_portfolio && <Badge status="MILESTONE" />}
                  </div>
                  <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                    {r.portfolio_project_id
                      ? `Maps to portfolio project: ${r.portfolio_project_id}`
                      : "Not mapped to a portfolio project"}
                    {" · "}
                    {r.auto_create_pr ? "Auto-PR on" : "Manual PR"}
                    {r.auto_merge ? " · Auto-merge on" : ""}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => toggleExpand(r)}
                    className="btn btn-ghost"
                    style={{ fontSize: "0.75rem" }}
                  >
                    {expanded === r.id ? "▲ Hide" : "▼ Commits"}
                  </button>
                  <button onClick={() => openEdit(r)} className="btn btn-ghost">Edit</button>
                  <button onClick={() => remove(r.id)} className="btn btn-danger">Remove</button>
                </div>
              </div>

              {/* Expanded commits */}
              {expanded === r.id && (
                <div className="mt-4">
                  <hr className="divider" />
                  <h3 className="text-xs font-semibold mb-3" style={{ color: "var(--muted)" }}>
                    RECENT COMMITS
                  </h3>
                  {!commits[r.id] ? (
                    <p className="text-xs" style={{ color: "var(--muted)" }}>Loading…</p>
                  ) : commits[r.id].length === 0 ? (
                    <p className="text-xs" style={{ color: "var(--muted)" }}>No commits yet.</p>
                  ) : (
                    <div className="space-y-2">
                      {commits[r.id].slice(0, 10).map((c) => (
                        <div
                          key={c.id}
                          className="flex items-start justify-between py-2"
                          style={{ borderBottom: "1px solid var(--border)" }}
                        >
                          <div className="min-w-0 mr-3">
                            <p className="text-sm truncate" title={c.message}>
                              {c.message.slice(0, 72)}
                            </p>
                            <p className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>
                              <code>{c.sha.slice(0, 7)}</code>
                              {c.error_message && (
                                <span className="ml-2" style={{ color: "#f85149" }} title={c.error_message}>
                                  ⚠ {c.error_message.slice(0, 80)}
                                </span>
                              )}
                            </p>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <Badge status={c.status} />
                            {(c.status === "queued" || c.status === "failed") && (
                              <button
                                onClick={() => triggerAnalysis(c.id, r.id)}
                                className="btn btn-ghost"
                                style={{ fontSize: "0.7rem", padding: "0.15rem 0.5rem" }}
                              >
                                Analyze
                              </button>
                            )}
                            {c.status === "analyzed" && (
                              <Link
                                href={`/analyses?commit_id=${c.id}`}
                                className="text-xs"
                                style={{ color: "var(--accent)" }}
                              >
                                View →
                              </Link>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
