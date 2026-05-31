import type { Metadata } from "next";
import "./globals.css";
import Footer from "@/components/Footer";
import CookieBanner from "@/components/CookieBanner";
import PageTransition from "@/components/PageTransition";

export const metadata: Metadata = {
  title: "Up2Code AI — Building Code Compliance",
  description: "Multi-agent AI system for automated building code compliance verification",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen flex flex-col">
          <div className="flex-1">
            <PageTransition>{children}</PageTransition>
          </div>
          <Footer />
        </div>
        <CookieBanner />
      </body>
    </html>
  );
}
