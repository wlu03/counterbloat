import "./globals.css";

export const metadata = { title: "Countercheck" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header><a href="/">Countercheck</a></header>
        {children}
      </body>
    </html>
  );
}
