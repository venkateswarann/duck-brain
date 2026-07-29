export default function TerminalPage() {
  return (
    <div className="page">
      <div className="page-title">
        <span>Terminal</span>
        <span className="muted">Disabled by default (security)</span>
      </div>
      <div className="placeholder">
        Web PTY will attach here when <code>allow_web_terminal</code> is enabled
        in duck config and <code>ALLOW_WEB_TERMINAL=1</code> is set. Use the SSH
        Connections page or a local shell for now.
      </div>
    </div>
  );
}
