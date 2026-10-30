import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "X-VibeBot — Autonomous X Growth & Drafting Studio",
  description: "Monitor niche conversations, draft in your authentic voice, and publish from an isolated X workspace.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
