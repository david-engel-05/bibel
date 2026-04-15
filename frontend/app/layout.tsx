import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { EB_Garamond } from "next/font/google";
import "./globals.css";

const geist = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const garamond = EB_Garamond({
  variable: "--font-serif",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Bibel KI",
  description: "Stelle Fragen zur Bibel und erhalte Antworten mit Bibelstellen.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="de"
      className={`${geist.variable} ${garamond.variable} h-full`}
      style={{ colorScheme: "dark", background: "#0c0b0a" }}
    >
      <body
        className="min-h-full flex flex-col antialiased"
        style={{ background: "#0c0b0a", color: "#f0ebe0" }}
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
