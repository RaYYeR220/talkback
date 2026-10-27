import type { Metadata, Viewport } from "next";
import { fontVariables } from "@/styles/fonts";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Talkback", template: "%s · Talkback" },
  description:
    "The editorial gallery for a whole matchday: agents find the stories, prove every line, clear it for every territory and cue it to the presenter.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={fontVariables}>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
