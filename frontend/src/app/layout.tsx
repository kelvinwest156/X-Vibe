import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VibeBot",
  description: "Autonomous X creator and engagement analytics",
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
