"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Overview" },
  { href: "/repositories", label: "Repositories" },
  { href: "/updates", label: "Updates" },
  { href: "/analyses", label: "Analyses" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <header
      style={{
        borderBottom: "1px solid var(--border)",
        background: "var(--surface)",
        position: "sticky",
        top: 0,
        zIndex: 40,
      }}
    >
      <div
        className="mx-auto max-w-6xl px-5 flex items-center gap-1"
        style={{ height: "3rem" }}
      >
        <span
          className="font-semibold text-sm mr-4"
          style={{ color: "var(--text)" }}
        >
          Portfolio AI
        </span>
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={`nav-link${pathname === l.href ? " active" : ""}`}
          >
            {l.label}
          </Link>
        ))}
      </div>
    </header>
  );
}
