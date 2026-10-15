import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { apiUrl } from "./config";
import { TelemetryProvider } from "./hooks/useTelemetry";
import SystemNodesPage from "./pages/SystemNodesPage";
import DevicesPage from "./pages/DevicesPage";
import ScriptsPage from "./pages/ScriptsPage";
import VizPage from "./pages/VizPage";
import CameraPage from "./pages/CameraPage";
import BoardPinsPage from "./pages/BoardPinsPage";
import ControlPage from "./pages/ControlPage";
import HostSystemPage from "./pages/HostSystemPage";
import TerminalPage from "./pages/TerminalPage";
import ConnectionsPage from "./pages/ConnectionsPage";
import HelpPage from "./pages/HelpPage";
import SettingsPage from "./pages/SettingsPage";
import SetupPage from "./pages/SetupPage";
import LogsPage from "./pages/LogsPage";
import CompanionPage from "./pages/CompanionPage";

const NAV = [
  { to: "/duck", label: "Duck", icon: "🦆" },
  { to: "/help", label: "Help", icon: "?" },
  { to: "/settings", label: "Settings", icon: "⚙" },
  { to: "/setup", label: "Setup", icon: "🔧" },
  { to: "/system/nodes", label: "System", icon: "▣" },
  { to: "/logs", label: "Logs", icon: "📋" },
  { to: "/scripts", label: "Scripts", icon: "⌘" },
  { to: "/viz", label: "Viz", icon: "◈" },
  { to: "/devices", label: "Devices", icon: "▦" },
  { to: "/camera", label: "Camera", icon: "◎" },
  { to: "/pins", label: "Pins", icon: "⎔" },
  { to: "/control", label: "Control", icon: "♟" },
  { to: "/host", label: "Host", icon: "☰" },
  { to: "/connections", label: "Conn", icon: "⇄" },
  { to: "/terminal", label: "Term", icon: ">_" },
];

export default function App() {
  const [robot, setRobot] = useState({ id: "…", name: "DCS" });
  const location = useLocation();
  const isViz = location.pathname === "/viz";

  useEffect(() => {
    fetch(apiUrl("/api/health"))
      .then((r) => r.json())
      .then((h) =>
        fetch(apiUrl("/api/config"))
          .then((r) => r.json())
          .then((c) => setRobot({ id: c.robot_id, name: c.robot_name }))
          .catch(() => setRobot({ id: h.robot_id, name: h.robot_name }))
      )
      .catch(() => undefined);
  }, []);

  return (
    <TelemetryProvider>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">DCS</div>
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `nav-item${isActive ? " active" : ""}`
              }
            >
              <span className="nav-icon">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </aside>
        <header className="header">
          <div className="header-left">
            <strong>
              {robot.id} — [{robot.name}]
            </strong>
            <span className="badge">Active</span>
          </div>
          <div className="muted">Duck Control System</div>
        </header>
        <main className="main">
          {/* Persistent 3D Viz Page Container */}
          <div
            style={{
              display: isViz ? "flex" : "none",
              flex: 1,
              height: "100%",
              width: "100%",
              flexDirection: "column",
            }}
          >
            <VizPage />
          </div>

          {/* Regular Routes Container */}
          <div
            style={{
              display: isViz ? "none" : "flex",
              flex: 1,
              height: "100%",
              width: "100%",
              flexDirection: "column",
            }}
          >
            <Routes>
              <Route path="/" element={<HelpPage />} />
              <Route path="/help" element={<HelpPage />} />
              <Route path="/duck" element={<CompanionPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/setup" element={<SetupPage />} />
              <Route path="/system/nodes" element={<SystemNodesPage />} />
              <Route path="/logs" element={<LogsPage />} />
              <Route path="/devices" element={<DevicesPage />} />
              <Route path="/scripts" element={<ScriptsPage />} />
              <Route path="/camera" element={<CameraPage />} />
              <Route path="/pins" element={<BoardPinsPage />} />
              <Route path="/control" element={<ControlPage />} />
              <Route path="/host" element={<HostSystemPage />} />
              <Route path="/network" element={<ConnectionsPage />} />
              <Route path="/bluetooth" element={<ConnectionsPage />} />
              <Route path="/terminal" element={<TerminalPage />} />
              <Route path="/connections" element={<ConnectionsPage />} />
            </Routes>
          </div>
        </main>
      </div>
    </TelemetryProvider>
  );
}
