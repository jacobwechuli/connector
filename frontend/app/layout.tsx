import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "AI Portfolio Maintainer",
  description: "Reviewable, evidence-based portfolio synchronization powered by AI.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Nav />
        <main className="page">{children}</main>
      </body>
    </html>
  );
}
