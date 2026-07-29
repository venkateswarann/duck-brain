import { useTelemetry } from "../hooks/useTelemetry";
import { Link } from "react-router-dom";

export default function HostSystemPage() {
  const { snapshot } = useTelemetry();
  const sys = snapshot?.system || {};

  return (
    <div className="page">
      <div className="page-title">
        <span>Host / System</span>
        <div className="btn-row">
          <Link className="btn" to="/network">
            Network settings
          </Link>
          <Link className="btn" to="/bluetooth">
            Bluetooth
          </Link>
          <span className="muted">{sys.hostname || "—"}</span>
        </div>
      </div>
      <div className="kv">
        <div className="k">Platform</div>
        <div>{sys.platform || "—"}</div>
        <div className="k">CPU</div>
        <div>{sys.cpu_percent ?? "—"}%</div>
        <div className="k">RAM</div>
        <div>
          {sys.ram
            ? `${sys.ram.used_mib} / ${sys.ram.total_mib} MiB (${sys.ram.percent}%)`
            : "—"}
        </div>
        <div className="k">Disk</div>
        <div>
          {sys.disk
            ? `${sys.disk.used_gb} / ${sys.disk.total_gb} GiB (${sys.disk.percent}%)`
            : "—"}
        </div>
        <div className="k">IPs</div>
        <div>
          {(sys.ips || [])
            .map((i: any) => `${i.iface}: ${i.ip}`)
            .join(" · ") || "—"}
        </div>
      </div>
      <div style={{ padding: 16 }}>
        <h3>Top processes</h3>
        <table className="table">
          <thead>
            <tr>
              <th>PID</th>
              <th>Name</th>
              <th>CPU</th>
              <th>Mem MiB</th>
            </tr>
          </thead>
          <tbody>
            {(sys.processes || []).map((p: any) => (
              <tr key={p.pid}>
                <td>{p.pid}</td>
                <td>{p.name}</td>
                <td>{p.cpu_percent}</td>
                <td>{p.memory_mib}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
