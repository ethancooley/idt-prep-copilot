import { Component, type ReactNode } from "react";

/** If any page throws while drawing, show what happened and a way back instead of a blank screen. */
export default class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page">
        <div className="notice" role="alert">
          <p><strong>Something on this page went wrong.</strong> {this.state.error.message}</p>
          <p style={{ marginTop: 8 }}>
            <a href="#/">Go to the review queue</a> or <button type="button" className="link-button" onClick={() => location.reload()}>reload the page</button>.
          </p>
        </div>
      </div>
    );
  }
}
