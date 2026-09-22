import type { Metadata } from "next";
import { Plus_Jakarta_Sans, Fraunces, DM_Sans, Fira_Code, Outfit } from "next/font/google";
import "./globals.css";
import { AppProvider } from "@/components/providers/AppProvider";
import { AppShell } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { ThemeInitScript } from "@/theme/ThemeInitScript";

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--ep-font-sans",
  display: "swap",
});

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--ep-font-serif",
  display: "swap",
});

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--ep-font-dm-sans",
  display: "swap",
});

const firaCode = Fira_Code({
  subsets: ["latin"],
  variable: "--ep-font-mono",
  display: "swap",
});

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--ep-font-outfit",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Episteck Home — Olin Family OS",
  description: "Personal and Family OS",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${plusJakarta.variable} ${fraunces.variable} ${dmSans.variable} ${firaCode.variable} ${outfit.variable}`}
      suppressHydrationWarning
    >
      <head>
        <ThemeInitScript />
      </head>
      <body>
        <ThemeProvider>
          <AppProvider>
            <AppShell>{children}</AppShell>
          </AppProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
