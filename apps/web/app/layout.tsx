import type { Metadata } from "next";
import "./globals.css";
import "./atelier.css";

export const metadata: Metadata = {
  title: "Cutroom — Video Clip Factory",
  description: "Find, frame, and finish the moments worth sharing.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

