import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./styles.css";

// Shared server-state cache (TanStack Query). Operator-console defaults: a short
// stale window so panels share a deduped cache without surprise refetches, one
// retry, and no refetch-on-focus (an operator tabbing back shouldn't re-hit the
// daemon). Individual queries override as needed (e.g. polled metrics).
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: false } },
});

// Last-resort boundary around the whole app. The section workspace has its own
// SectionErrorBoundary, but a throw in the shell (sidebar, connection bar,
// alerts popover, live-events consumer) would otherwise escape to a blank page.
// This renders a minimal, dependency-free recovery card instead.
class RootBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  override state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  override componentDidCatch(error: Error) {
    console.error("[SNDR GUI] unrecovered error:", error);
  }
  override render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          style={{
            maxWidth: 560,
            margin: "12vh auto",
            padding: "24px 28px",
            fontFamily: "system-ui, sans-serif",
            color: "#e7e7ea",
            background: "#1a1b1e",
            border: "1px solid #34353a",
            borderRadius: 12,
          }}
        >
          <h1 style={{ fontSize: 18, margin: "0 0 8px" }}>
            The control center hit an unexpected error
          </h1>
          <p style={{ color: "#9a9ba0", fontSize: 14, lineHeight: 1.5, margin: "0 0 16px" }}>
            A reload usually clears it. If it persists, check the daemon is
            reachable and report the message below.
          </p>
          <pre
            style={{
              fontSize: 12,
              color: "#c0392b",
              background: "#161719",
              border: "1px solid #34353a",
              borderRadius: 8,
              padding: "10px 12px",
              overflowX: "auto",
              whiteSpace: "pre-wrap",
            }}
          >
            {this.state.error.message}
          </pre>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              marginTop: 16,
              padding: "8px 16px",
              fontSize: 14,
              fontWeight: 600,
              color: "#fff",
              background: "#2563eb",
              border: 0,
              borderRadius: 8,
              cursor: "pointer",
            }}
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RootBoundary>
        <App />
      </RootBoundary>
    </QueryClientProvider>
  </React.StrictMode>
);
