import { useEffect, useState } from "react";
import { apiUrl } from "../config";

export default function ControlPage() {
  const [keymap, setKeymap] = useState<Record<string, any>>({});

  useEffect(() => {
    fetch(apiUrl("/api/input/keymap"))
      .then((r) => r.json())
      .then(setKeymap)
      .catch(() => undefined);
  }, []);

  return (
    <div className="page">
      <div className="page-title">
        <span>Control / Key map</span>
        <span className="muted">
          Pair Xbox via bluetoothctl on the host; Joy node comes next
        </span>
      </div>
      <div style={{ padding: 16 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Action</th>
              <th>Type</th>
              <th>ID</th>
              <th>Label</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(keymap).map(([action, spec]) => (
              <tr key={action}>
                <td>{action}</td>
                <td>{spec.type}</td>
                <td>{spec.id}</td>
                <td>{spec.label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
