import "./globals.css";

export const metadata = {
  title: 'SkillForge',
  description: 'Natural language to robot skill pipelines. Powered by NVIDIA Nemotron on Nebius.',
};

// Sets <html data-theme> before first paint so there's no flash of the wrong
// theme: an explicitly saved choice wins, otherwise the OS preference is used
// (dark is the fallback for browsers without prefers-color-scheme).
const themeScript = `(function(){try{var t=localStorage.getItem("sf-theme");if(t!=="dark"&&t!=="light"){t=window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";}document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme="dark";}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      {/* suppressHydrationWarning: the theme script sets data-theme on <html>
          before React hydrates, so the attribute legitimately differs from SSR. */}
      <body style={{ margin: 0, padding: 0 }}>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        {children}
      </body>
    </html>
  );
}
