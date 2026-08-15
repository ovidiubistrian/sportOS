export default function NotFound() {
  // Rendered when the Host header matches no published club, so it must not
  // assume any club branding exists.
  return (
    <html lang="en">
      <body
        style={{
          display: "grid",
          placeItems: "center",
          minHeight: "100vh",
          margin: 0,
          fontFamily: "system-ui, sans-serif",
          background: "#f6f7f9",
          color: "#10141a",
        }}
      >
        <main style={{ textAlign: "center", padding: "2rem" }}>
          <h1 style={{ fontSize: "1.125rem", fontWeight: 600 }}>Site not found</h1>
          <p style={{ color: "#59626e", fontSize: "0.875rem", marginTop: "0.5rem" }}>
            No club website is published on this address.
          </p>
        </main>
      </body>
    </html>
  );
}
