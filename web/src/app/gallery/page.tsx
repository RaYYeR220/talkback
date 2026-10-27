import type { Metadata } from "next";
import { Console } from "@/components/console/Console";

export const metadata: Metadata = {
  title: "Console",
  description: "The Talkback console: ten matches, the story board, the clearance matrix and the producer seat.",
};

export default function GalleryPage() {
  return <Console />;
}
