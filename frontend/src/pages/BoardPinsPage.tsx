import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config";

type Board = {
  id: string;
  name: string;
  pins: Array<{
    phys: number;
    bcm: number | null;
    name: string;
    type: string;
  }>;
};

type Pinout = {
  board: string;
  devices: Array<{
    id: string;
    type: string;
    pins: Record<string, number>;
    mode?: string;
  }>;
};

export default function BoardPinsPage() {
  const [boards, setBoards] = useState<Board[]>([]);
  const [pinout, setPinout] = useState<Pinout>({ board: "rpi5", devices: [] });
  const [newDev, setNewDev] = useState({
    id: "status_led",
    type: "led",
    bcm: 17,
  });

  useEffect(() => {
    fetch(apiUrl("/api/boards"))
      .then((r) => r.json())
      .then(setBoards)
      .catch(() => undefined);
    fetch(apiUrl("/api/pinout"))
      .then((r) => r.json())
      .then(setPinout)
      .catch(() => undefined);
  }, []);

  const board = boards.find((b) => b.id === pinout.board) || boards[0];
  const used = useMemo(() => {
    const s = new Set<number>();
    for (const d of pinout.devices || []) {
      Object.values(d.pins || {}).forEach((p) => s.add(Number(p)));
    }
    return s;
  }, [pinout]);

  const left = (board?.pins || []).filter((p) => p.phys % 2 === 1);
  const right = (board?.pins || []).filter((p) => p.phys % 2 === 0);

  const save = async (next: Pinout) => {
    setPinout(next);
    await fetch(apiUrl("/api/pinout"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    });
  };

  const addDevice = async () => {
    const next = {
      ...pinout,
      devices: [
        ...(pinout.devices || []),
        {
          id: newDev.id,
          type: newDev.type,
          pins: { signal: newDev.bcm },
          mode: "OUT",
        },
      ],
    };
    await save(next);
  };

  const exportSchema = () => {
    const blob = new Blob([JSON.stringify(pinout, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `pinout-${pinout.board}.json`;
    a.click();
  };

  const importSchema = async (file: File) => {
    const text = await file.text();
    const data = JSON.parse(text);
    await fetch(apiUrl("/api/pinout/import"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    setPinout(data);
  };

  return (
    <div className="page">
      <div className="page-title">
        <span>Board Pins</span>
        <div className="btn-row">
          <select
            className="btn"
            value={pinout.board}
            onChange={(e) => save({ ...pinout, board: e.target.value })}
          >
            {boards.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          <button className="btn" onClick={exportSchema}>
            Export
          </button>
          <label className="btn" style={{ cursor: "pointer" }}>
            Import
            <input
              type="file"
              accept="application/json"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importSchema(f);
              }}
            />
          </label>
        </div>
      </div>
      <div className="split split-2">
        <div className="panel">
          <div className="pin-grid">
            <div>
              {left.map((p) => (
                <div
                  key={p.phys}
                  className={`pin ${p.type} ${
                    p.bcm != null && used.has(p.bcm) ? "used" : ""
                  }`}
                  title={`phys ${p.phys}`}
                >
                  <strong>{p.phys}</strong> {p.name}
                  {p.bcm != null ? ` (BCM ${p.bcm})` : ""}
                </div>
              ))}
            </div>
            <div className="muted" style={{ textAlign: "center", paddingTop: 40 }}>
              {board?.name || "Board"}
            </div>
            <div>
              {right.map((p) => (
                <div
                  key={p.phys}
                  className={`pin ${p.type} ${
                    p.bcm != null && used.has(p.bcm) ? "used" : ""
                  }`}
                >
                  <strong>{p.phys}</strong> {p.name}
                  {p.bcm != null ? ` (BCM ${p.bcm})` : ""}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="panel" style={{ padding: 16 }}>
          <h3 style={{ marginTop: 0 }}>Add device</h3>
          <div className="kv">
            <div className="k">ID</div>
            <input
              className="btn"
              value={newDev.id}
              onChange={(e) => setNewDev({ ...newDev, id: e.target.value })}
            />
            <div className="k">Type</div>
            <select
              className="btn"
              value={newDev.type}
              onChange={(e) => setNewDev({ ...newDev, type: e.target.value })}
            >
              <option value="led">LED</option>
              <option value="digital_input">Digital input</option>
              <option value="actuator">Actuator / PWM</option>
            </select>
            <div className="k">BCM pin</div>
            <input
              className="btn"
              type="number"
              value={newDev.bcm}
              onChange={(e) =>
                setNewDev({ ...newDev, bcm: Number(e.target.value) })
              }
            />
          </div>
          <button className="btn primary" onClick={addDevice}>
            Add & save
          </button>
          <h3>Connected devices</h3>
          <pre className="log-view">
            {JSON.stringify(pinout.devices || [], null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}
