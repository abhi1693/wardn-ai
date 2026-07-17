"use client";

export default function GlobalError({ reset }: { reset: () => void }) {
  return (
    <html lang="en">
      <body>
        <main style={{ fontFamily: "sans-serif", margin: "80px auto", maxWidth: 560, padding: 24 }}>
          <h1>Wardn AI could not start</h1>
          <p>The application encountered an unexpected error. Try loading it again.</p>
          <button onClick={reset} type="button">
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
