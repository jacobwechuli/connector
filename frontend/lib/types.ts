/**
 * Shared TypeScript types mirroring the backend Pydantic schemas.
 */

export interface Repository {
  id: number;
  owner: string;
  name: string;
  portfolio_project_id: string | null;
  enabled: boolean;
  auto_create_pr: boolean;
  auto_merge: boolean;
  is_portfolio: boolean;
}

export interface GitHubAccount {
  connected: boolean;
  login: string | null;
  avatar_url: string | null;
  message: string | null;
}

export interface GitHubRepository {
  owner: string;
  name: string;
  full_name: string;
  private: boolean;
  default_branch: string;
  connected: boolean;
}

export interface Commit {
  id: number;
  repository_id: number;
  sha: string;
  message: string;
  status: "queued" | "analyzed" | "failed" | string;
  error_message: string | null;
  processed_at: string | null;
}

export interface Analysis {
  id: number;
  commit_id: number;
  portfolio_worthy: boolean;
  confidence: number;
  significance: "IGNORE" | "MINOR" | "MODERATE" | "MAJOR" | "MILESTONE";
  reasoning_summary: string;
  model: string;
  prompt_version: string;
  raw_result: Record<string, unknown>;
  created_at: string;
}

export interface PortfolioUpdate {
  id: number;
  commit_id: number;
  operations: { operations: Operation[] };
  diff: string | null;
  status:
    | "pending"
    | "approved"
    | "rejected"
    | "pr_created"
    | "merged"
    | "reverted"
    | "pr_closed"
    | string;
  validation_result: Record<string, unknown>;
  branch: string | null;
  pr_number: number | null;
  error_message: string | null;
  created_at: string;
}

export interface Operation {
  type: string;
  project_id?: string;
  changes?: Record<string, unknown>;
  skill?: string;
  title?: string;
  description?: string;
  date?: string;
}

export interface WorkflowEvent {
  id: number;
  repository_id: number | null;
  commit_id: number | null;
  update_id: number | null;
  stage: string;
  detail: string | null;
  created_at: string;
}
