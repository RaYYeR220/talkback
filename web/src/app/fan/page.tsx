import type { Metadata } from "next";
import { FanView } from "@/components/fan/FanView";

export const metadata: Metadata = {
  title: "Your matchday",
  description: "A fan feed cleared for your territory, in your language, at your depth.",
};

export default function FanPage() {
  return <FanView />;
}
