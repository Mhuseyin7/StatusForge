"use client";

import { useMemo, useState } from "react";
import { operationalCount, type MonitorState } from "../lib/monitor";

type Monitor = { name: string; status: MonitorState; latency: number; uptime: string; kind: string };

const monitors: Monitor[] = [
  { name: "Public API", status: "UP", latency: 82, uptime: "99.99%", kind: "HTTPS" },
  { name: "Web application", status: "UP", latency: 128, uptime: "99.98%", kind: "HTTPS" },
  { name: "Payments webhook", status: "PENDING", latency: 0, uptime: "—", kind: "HEARTBEAT" }
];

const navigation = ["Overview", "Monitors", "Incidents", "Status Pages", "Maintenance", "Notifications", "Team", "Audit Logs", "Settings"];

export function Dashboard() {
  const [active, setActive] = useState("Overview");
  const [dark, setDark] = useState(true);
  const summary = useMemo(() => ({ up: operationalCount(monitors.map((monitor) => monitor.status)), total: monitors.length }), []);

  return <main className={dark ? "shell theme-dark" : "shell"}>
    <aside className="sidebar" aria-label="Primary navigation">
      <a className="brand" href="#overview"><span className="brand-mark">S</span><span>StatusForge</span></a>
      <span className="workspace">ACME ENGINEERING</span>
      <nav>{navigation.map((item) => <button className={active === item ? "nav-item active" : "nav-item"} onClick={() => setActive(item)} key={item}>{item}</button>)}</nav>
      <button className="theme-switch" onClick={() => setDark(!dark)} aria-pressed={dark}>Switch to {dark ? "light" : "dark"} theme</button>
    </aside>
    <section className="content" id="overview">
      <header className="topbar"><div><p className="eyebrow">OPERATIONS / OVERVIEW</p><h1>Reliability at a glance</h1></div><button className="primary">+ New monitor</button></header>
      <div className="notice"><span className="pulse" /> All systems operational. Last check received moments ago.</div>
      <section className="stats" aria-label="Monitor summary">
        <Metric label="Monitors up" value={`${summary.up}/${summary.total}`} detail="No active outages" />
        <Metric label="Active incidents" value="0" detail="Last 30 days" />
        <Metric label="Average uptime" value="99.98%" detail="Rolling 90 days" />
        <Metric label="Response time" value="105 ms" detail="P50 across HTTP monitors" />
      </section>
      <section className="panel"><div className="panel-heading"><div><h2>Monitors</h2><p>Service health and recent response times.</p></div><button className="quiet">View all monitors →</button></div>
        <div className="table-wrap"><table><thead><tr><th>Monitor</th><th>Status</th><th>Type</th><th>Response</th><th>Uptime</th><th aria-label="Actions" /></tr></thead><tbody>{monitors.map((monitor) => <tr key={monitor.name}><td><strong>{monitor.name}</strong><small>Checked less than a minute ago</small></td><td><Status status={monitor.status} /></td><td>{monitor.kind}</td><td>{monitor.latency ? `${monitor.latency} ms` : "Awaiting signal"}</td><td>{monitor.uptime}</td><td><button className="icon-button" aria-label={`Open ${monitor.name}`}>→</button></td></tr>)}</tbody></table></div>
      </section>
      <section className="lower-grid"><article className="panel"><div className="panel-heading"><div><h2>Response time</h2><p>Last 24 hours</p></div><span className="trend">↓ 12%</span></div><div className="chart" aria-label="Response time chart"><svg viewBox="0 0 660 180" role="img"><title>Response time over the last 24 hours</title><path d="M0 126 C42 118 54 96 92 110 S140 143 178 112 S234 69 272 96 S320 124 360 86 S425 66 462 89 S523 127 560 75 S620 54 660 70" fill="none" stroke="currentColor" strokeWidth="3"/><path d="M0 126 C42 118 54 96 92 110 S140 143 178 112 S234 69 272 96 S320 124 360 86 S425 66 462 89 S523 127 560 75 S620 54 660 70 V180 H0Z" fill="currentColor" opacity=".1" /></svg></div></article>
        <article className="panel"><div className="panel-heading"><div><h2>Incident timeline</h2><p>Nothing needs attention.</p></div></div><div className="empty"><span>✓</span><strong>Quiet and healthy</strong><p>New incidents and updates will appear here.</p></div></article></section>
    </section>
  </main>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="metric"><p>{label}</p><strong>{value}</strong><small>{detail}</small></article>; }
function Status({ status }: { status: Monitor["status"] }) { return <span className={`status ${status.toLowerCase()}`}><i />{status === "PENDING" ? "Pending" : status === "UP" ? "Operational" : "Outage"}</span>; }
