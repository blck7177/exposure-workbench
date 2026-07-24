import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

// Auth is optional at build/run time: with no publishable key (e.g. the public
// read-only demo) we skip ClerkProvider entirely so the page still renders.
const clerkEnabled = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Exposure Workbench",
  description: "Portfolio exposure workflow — analytics + LLM reporting",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const body = (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-[#0d1117] text-[#e6edf3] h-screen overflow-hidden`}
      >
        {children}
      </body>
    </html>
  );
  return clerkEnabled ? <ClerkProvider>{body}</ClerkProvider> : body;
}
