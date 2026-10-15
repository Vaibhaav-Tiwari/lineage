import type { Metadata } from "next";
import { Courier_Prime } from "next/font/google";
import "./globals.css";

// Libre Caslon Condensed is newer than next/font's catalogue, so it loads from Google Fonts directly.
const CASLON = "https://fonts.googleapis.com/css2?family=Libre+Caslon+Condensed:ital,wght@0,400..700;1,400..700&display=swap";
const typed = Courier_Prime({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-typed" });

export const metadata: Metadata = {
  title: "Lineage",
  description: "A company brain that remembers why — and un-learns when the truth changes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={typed.variable}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link rel="stylesheet" href={CASLON} />
      </head>
      <body>{children}</body>
    </html>
  );
}
