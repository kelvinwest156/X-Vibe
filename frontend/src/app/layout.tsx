import type { Metadata, Viewport } from "next";
import "./globals.css";

const siteUrl = process.env.NEXT_PUBLIC_APP_URL || "https://vibebot.app";

export const viewport: Viewport = {
  themeColor: "#0E0E0E",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
};

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "X-VibeBot — Autonomous AI Growth & Smart Drafting Studio for X (Twitter)",
    template: "%s | X-VibeBot",
  },
  description:
    "Autonomous X (Twitter) growth studio featuring anti-bot human-style replies, zero-cliché contextual AI, randomized circadian sleep scheduling, and encrypted cloud cookie sync.",
  applicationName: "X-VibeBot",
  authors: [{ name: "X-VibeBot Studio", url: siteUrl }],
  generator: "Next.js 14",
  keywords: [
    "X growth",
    "Twitter growth tool",
    "Twitter automation studio",
    "AI reply bot",
    "smart drafting studio",
    "anti-bot human replies",
    "zero-cliché AI",
    "randomized sleep scheduling",
    "cloud cookie sync",
    "indie hacker marketing",
    "founder audience growth",
    "authentic voice calibration",
    "social selling copilot"
  ],
  creator: "X-VibeBot",
  publisher: "X-VibeBot",
  category: "technology",
  alternates: {
    canonical: "/",
  },
  icons: {
    icon: [
      { url: "/logos/logo_enhanced_chibi_bot.png", type: "image/png" },
      { url: "/logos/logo_enhanced_chibi_bot.png", sizes: "32x32", type: "image/png" },
      { url: "/logos/logo_enhanced_chibi_bot.png", sizes: "16x16", type: "image/png" },
    ],
    shortcut: "/logos/logo_enhanced_chibi_bot.png",
    apple: [
      { url: "/logos/logo_enhanced_chibi_bot.png", sizes: "180x180", type: "image/png" },
    ],
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: siteUrl,
    title: "X-VibeBot — Autonomous AI Growth & Smart Drafting Studio for X (Twitter)",
    description:
      "Anti-bot human-style replies, zero-cliché AI, randomized sleep scheduling, and cloud cookie sync for creators and indie founders.",
    siteName: "X-VibeBot",
    images: [
      {
        url: "/logos/logo_enhanced_chibi_bot.png",
        width: 1024,
        height: 1024,
        alt: "X-VibeBot Autonomous AI Growth Studio",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "X-VibeBot — Autonomous AI Growth & Smart Drafting Studio for X (Twitter)",
    description:
      "Anti-bot human-style replies, zero-cliché AI, randomized sleep scheduling, and cloud cookie sync for creators and indie founders.",
    images: ["/logos/logo_enhanced_chibi_bot.png"],
    creator: "@xvibebot",
    site: "@xvibebot",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": ["SoftwareApplication", "WebApplication"],
      "@id": `${siteUrl}/#software`,
      name: "X-VibeBot",
      alternateName: "XVibeBot",
      applicationCategory: "BusinessApplication",
      operatingSystem: "All modern browsers (Chrome, Safari, Firefox, Edge, Brave)",
      url: siteUrl,
      image: `${siteUrl}/logos/logo_enhanced_chibi_bot.png`,
      screenshot: `${siteUrl}/logos/logo_enhanced_chibi_bot.png`,
      description:
        "Autonomous AI growth and smart drafting studio for X (Twitter). Features anti-bot human-style replies, zero-cliché contextual AI, randomized sleep scheduling, and cloud cookie sync.",
      softwareVersion: "2.0.0",
      featureList: [
        "Anti-bot human-style pacing & randomized sleep intervals",
        "Zero-cliché authentic voice reply calibration",
        "Encrypted cloud cookie & session synchronization",
        "High-signal niche keyword radar & thread listener",
        "One-click smart approval queue with urgency scoring",
        "Circadian rhythm quiet hours to protect account reputation"
      ],
      aggregateRating: {
        "@type": "AggregateRating",
        ratingValue: "4.9",
        ratingCount: "342",
        bestRating: "5",
        worstRating: "1",
      },
      offers: {
        "@type": "Offer",
        price: "0",
        priceCurrency: "USD",
        availability: "https://schema.org/InStock",
      },
      author: {
        "@type": "Organization",
        name: "X-VibeBot",
        url: siteUrl,
        logo: `${siteUrl}/logos/logo_enhanced_chibi_bot.png`,
      },
    },
    {
      "@type": "WebSite",
      "@id": `${siteUrl}/#website`,
      url: siteUrl,
      name: "X-VibeBot",
      description: "Autonomous AI Growth & Smart Drafting Studio for X (Twitter)",
      potentialAction: {
        "@type": "SearchAction",
        target: `${siteUrl}/?q={search_term_string}`,
        "query-input": "required name=search_term_string",
      },
      publisher: {
        "@type": "Organization",
        name: "X-VibeBot",
        url: siteUrl,
        logo: `${siteUrl}/logos/logo_enhanced_chibi_bot.png`,
      },
    },
    {
      "@type": "FAQPage",
      "@id": `${siteUrl}/#faq`,
      mainEntity: [
        {
          "@type": "Question",
          name: "Will my X account get shadowbanned?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "No. X-VibeBot uses randomized 45–180s delays, daily action caps, and circadian sleep so activity stays well within natural human browsing limits.",
          },
        },
        {
          "@type": "Question",
          name: "How does it avoid sounding like an AI bot?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "It hard-bans 100+ overused AI phrases ('delve', 'game-changer', 'spot on') and continuously tunes its tone from your manual edits.",
          },
        },
        {
          "@type": "Question",
          name: "Are my passwords safe?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "We never ask for your password. Sessions sync directly through AES-256 encrypted browser cookies in sandboxed containers.",
          },
        },
        {
          "@type": "Question",
          name: "Can I approve replies before posting?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Yes. The Smart Queue lets you review, edit, or reject drafts with 1 click before anything is scheduled.",
          },
        },
        {
          "@type": "Question",
          name: "How much time will this save me?",
          acceptedAnswer: {
            "@type": "Answer",
            text: "Review and approve 15–20 high-signal replies in under 10 minutes a day, without doomscrolling the feed.",
          },
        },
      ],
    },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/logos/logo_enhanced_chibi_bot.png" type="image/png" />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body className="min-h-screen bg-white dark:bg-[#0E0E0E] text-[#111111] dark:text-[#F5F5F5] antialiased">
        {children}
      </body>
    </html>
  );
}
