import type { Metadata } from "next";
import { Plus_Jakarta_Sans, Fraunces, DM_Sans, Fira_Code, Outfit } from "next/font/google";
import "./globals.css";
import { AppProvider } from "@/components/providers/AppProvider";
import { AppShell } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { ThemeInitScript } from "@/theme/ThemeInitScript";
import { headers } from 'next/headers';
import { redirect } from 'next/navigation';
import { getBootstrapForRequest } from '@/integration/home/bootstrap.server';
import { ServiceUnavailableBoundary } from '@/integration/components/boundaries/ServiceUnavailableBoundary';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';

export const dynamic = 'force-dynamic';

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

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [result, requestHeaders] = await Promise.all([getBootstrapForRequest(), headers()]);
  if (result.errorCode === 'SESSION_REQUIRED' || result.errorCode === 'SESSION_INVALID') {
    redirect(new URL('/login', SERVER_CONFIGURATION.publicOrigin).toString());
  }
  const bootstrap = result.delivery === 'READY' ? result.data : undefined;
  const nonce = requestHeaders.get('x-nonce') ?? undefined;

  return (
    <html
      lang="en"
      className={`${plusJakarta.variable} ${fraunces.variable} ${dmSans.variable} ${firaCode.variable} ${outfit.variable}`}
      suppressHydrationWarning
    >
      <head>
        <ThemeInitScript nonce={nonce} />
      </head>
      <body>
        <ThemeProvider>
          {bootstrap ? (
            <AppProvider bootstrap={bootstrap}>
              <AppShell>{children}</AppShell>
            </AppProvider>
          ) : (
            <AppShell><ServiceUnavailableBoundary /></AppShell>
          )}
        </ThemeProvider>
      </body>
    </html>
  );
}
