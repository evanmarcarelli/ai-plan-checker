import type { Metadata } from "next";
import "./globals.css";
import Footer from "@/components/Footer";
import CookieBanner from "@/components/CookieBanner";

export const metadata: Metadata = {
  title: "AI Plan Checker — Building Code Compliance",
  description: "Multi-agent AI system for automated building code compliance verification",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen flex flex-col">
          <div className="flex-1">{children}</div>
          <Footer />
        </div>
        <CookieBanner />
      </body>
    </html>
  );
}
