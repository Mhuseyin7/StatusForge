type StatusPage = {
  name: string;
  description: string | null;
  theme: string;
  overall_status: "UP" | "DOWN";
  components: Array<{ name: string; status: string }>;
  incidents: Array<{ title: string; status: string; severity: string; started_at: string }>;
};

export const dynamic = "force-dynamic";

export default async function PublicStatusPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const apiUrl = process.env.API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL || "http://api:8000";
  const response = await fetch(`${apiUrl}/api/v1/status/${encodeURIComponent(slug)}`, { next: { revalidate: 30 } });
  if (!response.ok) return <main className="public-status"><h1>Status page unavailable</h1><p>This status page does not exist or is not published.</p></main>;
  const page: StatusPage = await response.json();
  const operational = page.overall_status === "UP";
  return <main className={`public-status ${page.theme === "dark" ? "theme-dark" : ""}`}><header className="public-header"><Link className="brand" href="/"><span className="brand-mark">S</span><span>{page.name}</span></Link><span className={operational ? "public-state up" : "public-state down"}>{operational ? "All systems operational" : "Service disruption"}</span></header><section className="public-hero"><h1>{page.name}</h1>{page.description && <p>{page.description}</p>}</section><section className="public-panel"><h2>Components</h2>{page.components.length ? page.components.map((component) => <div className="public-component" key={component.name}><span>{component.name}</span><strong className={component.status === "UP" ? "up" : "down"}>{component.status}</strong></div>) : <p>No components are published yet.</p>}</section><section className="public-panel"><h2>Active incidents</h2>{page.incidents.length ? page.incidents.map((incident) => <article className="public-incident" key={`${incident.title}-${incident.started_at}`}><strong>{incident.title}</strong><span>{incident.severity} · {incident.status}</span><time dateTime={incident.started_at}>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(incident.started_at))}</time></article>) : <p>No active incidents.</p>}</section><footer>Powered by StatusForge</footer></main>;
}
import Link from "next/link";

