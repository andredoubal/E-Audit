import { useCallback, useEffect, useRef, useState } from "react";
import { getLoop, uploadDocument, type LoopState } from "../api";

export default function UploadsPanel({ id, onUploaded }: { id: string; onUploaded: () => void }) {
  const [loop, setLoop] = useState<LoopState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => { getLoop(id).then(setLoop).catch(() => {}); }, [id]);
  useEffect(load, [load]);

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setErr("");
    try {
      for (const f of Array.from(files)) await uploadDocument(id, f);
      load();
      onUploaded();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed.");
    } finally { setBusy(false); }
  };

  // Superseded uploads are history, not evidence — a corrected resubmission replaces the file
  // it corrects, and listing both would suggest two documents arrived when one did.
  const received = (loop?.documents ?? []).filter((doc) => !doc.superseded);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Documents received</h2>
        <span className="pill status">
          {received.length ? `${received.length} on file` : "nothing yet"}
        </span>
      </div>
      <div className="panel-body">
        <div
          className={"dropzone" + (drag ? " over" : "")}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
          onClick={() => fileRef.current?.click()}
        >
          <input ref={fileRef} type="file" multiple accept=".xlsx,.xlsm,.csv,.tsv"
                 style={{ display: "none" }}
                 onChange={(e) => send(e.target.files)} />
          <b>{busy ? "Reading…" : "Drop the taxpayer's spreadsheets here"}</b>
          <span className="sub">or click to choose — .xlsx, .xlsm, .csv</span>
        </div>
        {err && <div className="callout warn">{err}</div>}

        {!!received.length && (
          <div className="doclist">
            {received.map((doc) => (
              <div className="docrow" key={doc.id}>
                <b>{doc.filename}</b>
                <span className="sub">
                  {doc.row_count} rows · {doc.columns?.length ?? 0} columns
                </span>
                {!!doc.columns?.length && (
                  <div className="cols">
                    {doc.columns.map((c: string) => <span className="ct" key={c}>{c}</span>)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <p className="detail-note">
          Each file is read into columns and rows on arrival. Everything downstream — the
          completeness check, the agents and your own calculations — works from that reading.
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------------ the page */
