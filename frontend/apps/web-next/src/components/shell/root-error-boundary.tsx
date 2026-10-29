import { Component, type ErrorInfo, type ReactNode } from "react";
import { navigateTo } from "@/lib/navigate-to";

/** Last resort for provider failures, independent of i18n and UI context. */
export class RootErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Eneo could not render", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main
        lang="en"
        style={{
          display: "flex",
          minHeight: "100vh",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          fontFamily: "system-ui, sans-serif",
          textAlign: "center",
          padding: "2rem"
        }}
      >
        <title>Eneo</title>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Something went wrong</h1>
        <button
          type="button"
          onClick={() => navigateTo(location.pathname + location.search)}
          style={{
            cursor: "pointer",
            borderRadius: "0.5rem",
            border: "1px solid currentColor",
            minHeight: "44px",
            padding: "0.5rem 1rem"
          }}
        >
          Try again
        </button>
      </main>
    );
  }
}
