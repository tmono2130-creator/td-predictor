import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NFL PM | NFL Touchdown Prediction Analytics",
  description: "NFL touchdown estimates, matchup analysis, parlay probabilities, and market comparisons.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className="h-full"
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
