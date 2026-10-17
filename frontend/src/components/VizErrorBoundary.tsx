import { Component, type ReactNode } from "react";

/** Keeps a 3D viewer failure (e.g. no WebGL on this GPU/browser) from blanking the whole app. */
export default class VizErrorBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };

  static getDerivedStateFromError(err: unknown) {
    return { error: err instanceof Error ? err.message : String(err) };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 24 }}>
          <h3 style={{ marginTop: 0 }}>3D view unavailable</h3>
          <p className="muted">
            This browser couldn't start WebGL ({this.state.error}). The other pages work normally. Try enabling hardware
            acceleration, or open chrome://gpu to see why WebGL is blocked.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
