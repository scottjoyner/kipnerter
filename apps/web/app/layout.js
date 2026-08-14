import "./globals.css";

export const metadata = {
  title: "Kipnerter",
  description: "Public web and AI platform gateway for Kipnerter.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
