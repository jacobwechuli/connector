"use client";

interface Props {
  status: string;
}

const MAP: Record<string, string> = {
  pending: "badge-pending",
  approved: "badge-approved",
  pr_created: "badge-pr_created",
  merged: "badge-merged",
  rejected: "badge-rejected",
  pr_closed: "badge-pr_closed",
  reverted: "badge-reverted",
  analyzed: "badge-analyzed",
  queued: "badge-queued",
  failed: "badge-failed",
  MAJOR: "badge-major",
  MILESTONE: "badge-milestone",
  MODERATE: "badge-moderate",
  MINOR: "badge-minor",
  IGNORE: "badge-ignore",
};

export default function Badge({ status }: Props) {
  const cls = MAP[status] ?? "badge-ghost";
  return (
    <span className={`badge ${cls}`} style={{ textTransform: "capitalize" }}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
