/**
 * Typed API client for the AI Portfolio Maintainer backend.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API = `${BASE}/api`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Repositories
export const getRepositories = () => request<import("./types").Repository[]>("/repositories");
export const addRepository = (body: object) =>
  request<import("./types").Repository>("/repositories", { method: "POST", body: JSON.stringify(body) });
export const updateRepository = (id: number, body: object) =>
  request<import("./types").Repository>(`/repositories/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteRepository = (id: number) =>
  request<void>(`/repositories/${id}`, { method: "DELETE" });
export const getGitHubStatus = () => request<import("./types").GitHubAccount>("/github/status");
export const getGitHubRepositories = () => request<import("./types").GitHubRepository[]>("/github/repositories");

// Commits
export const getRepositoryCommits = (repoId: number) =>
  request<import("./types").Commit[]>(`/repositories/${repoId}/commits`);
export const analyzeCommit = (commitId: number) =>
  request<{ status: string }>(`/commits/${commitId}/analyze`, { method: "POST" });
export const syncRepository = (repoId: number) =>
  request<{ status: string; commits: number }>(`/repositories/${repoId}/sync`, { method: "POST" });
export const getCommitAnalysis = (commitId: number) =>
  request<import("./types").Analysis>(`/commits/${commitId}/analysis`);

// Analyses
export const getAnalyses = () =>
  request<import("./types").Analysis[]>("/analyses");

// Updates
export const getUpdates = () =>
  request<import("./types").PortfolioUpdate[]>("/updates");
export const getUpdate = (id: number) =>
  request<import("./types").PortfolioUpdate>(`/updates/${id}`);
export const approveUpdate = (id: number) =>
  request<{ status: string }>(`/updates/${id}/approve`, { method: "POST" });
export const rejectUpdate = (id: number) =>
  request<{ status: string }>(`/updates/${id}/reject`, { method: "POST" });
export const createPR = (id: number) =>
  request<{ status: string; pr_number?: number }>(`/updates/${id}/create-pr`, { method: "POST" });
export const revertUpdate = (id: number) =>
  request<{ status: string }>(`/updates/${id}/revert`, { method: "POST" });

// Activity
export const getActivity = (limit = 50) =>
  request<import("./types").WorkflowEvent[]>(`/activity?limit=${limit}`);

// Health
export const getHealth = () => request<{ status: string }>("/health");
