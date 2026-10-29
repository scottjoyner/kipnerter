import PublicChat from "./public-chat";
export const metadata = {
  title: "Kipnerter — Local AI Chat",
  description: "Public, local-first AI chat with LFM3 1.7B, WebGPU and SensorGraft browser memory.",
};
export default function Home() { return <PublicChat />; }
