import "./globals.css";
import Chrome from "./chrome";

export const metadata = {
  title: "UK Fine Wine Deal Pricer",
  description: "Operator console",
};

export const viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }) {
  return (
    <html lang="en-GB">
      <body>
        <Chrome>{children}</Chrome>
      </body>
    </html>
  );
}
