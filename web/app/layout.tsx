import type { Metadata } from "next";
import { Courier_Prime, Libre_Caslon_Display, Libre_Caslon_Text } from "next/font/google";
import "./globals.css";

const display = Libre_Caslon_Display({ subsets: ["latin"], weight: "400", variable: "--font-display" });
const text = Libre_Caslon_Text({ subsets: ["latin"], weight: ["400", "700"], style: ["normal", "italic"], variable: "--font-text" });
const typed = Courier_Prime({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-typed" });

export const metadata: Metadata = {
  title: "Lineage",
  description: "A company brain that remembers why — and un-learns when the truth changes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${text.variable} ${typed.variable}`}>
      <body>{children}</body>
    </html>
  );
}
