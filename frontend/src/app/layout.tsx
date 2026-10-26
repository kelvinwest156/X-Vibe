import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "X-VibeBot · AI Command & Analytics BI",
  description: "Autonomous X (Twitter) Creator, Thread Synthesizer & Engagement Analytics Dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased selection:bg-sky-500/20 selection:text-sky-300">
        {children}
      </body>
    </html>
  );
}
