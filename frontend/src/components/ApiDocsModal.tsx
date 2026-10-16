import { IconX } from "./Icons";

export function ApiDocsModal({ onClose, apiInfo }: { onClose: () => void; apiInfo: Record<string, unknown> | null }) {
  const origin = window.location.origin;
  const endpoints = (apiInfo?.endpoints as Record<string, string> | undefined) ?? {};
  return (
    <div className="scrim center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="REST API documentation">
        <div className="drawer-head">
          <div className="col" style={{ gap: 4, flexGrow: 1 }}>
            <span className="eyebrow">DDI-CDI Converter API {apiInfo?.version ? `v${apiInfo.version as string}` : ""}</span>
            <h2>REST API</h2>
            <p>Everything the editor does goes through these endpoints. Interactive docs: <a href={`${origin}/docs`} target="_blank" rel="noreferrer">{origin}/docs</a></p>
          </div>
          <button type="button" className="btn" style={{ width: 32, padding: 0, justifyContent: "center" }} aria-label="Close" onClick={onClose}><IconX /></button>
        </div>
        <div className="drawer-body">
          <h3 style={{ fontSize: 14 }}>One shot (compatible with the original app)</h3>
          <pre>{`curl -F file=@ESS11-subset.sav -F max_rows=5 \\
     -F 'variable_roles={"idno":"identifier"}' -F include_statistics=true \\
     ${origin}/api/convert -o ESS11-subset_DDICDI.jsonld`}</pre>
          <h3 style={{ fontSize: 14 }}>Session style (what this editor uses)</h3>
          <table>
            <thead><tr><th>Endpoint</th><th>Purpose</th></tr></thead>
            <tbody>
              {Object.entries(endpoints).map(([k, v]) => (
                <tr key={k}><td className="mono" style={{ whiteSpace: "nowrap" }}>{k}</td><td>{v}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>
            Output is DDI-CDI JSON-LD (<span className="mono">application/ld+json</span>), downloaded as <span className="mono">&lt;file&gt;_DDICDI.jsonld</span>.
          </p>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>
            Authentication: {String(apiInfo?.authentication ?? "none")}. Set <span className="mono">DDI_API_KEY</span> on the server and enter the key under Options to enable it.
          </p>
        </div>
      </div>
    </div>
  );
}
