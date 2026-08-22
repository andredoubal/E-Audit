import { useCallback, useEffect, useRef, useState } from "react";
import { getLoop, getZatca, removeZatca, uploadDocument, uploadZatca,
         type LoopState, type ZatcaState } from "../api";

/** The spreadsheets the investigation runs on, and where they came from.
 *
 *  Two different files with two different jobs, so they get two slots rather than one:
 *  the taxpayer's listing **is** the population every rule is applied to, and ZATCA's own
 *  records are what it is matched against. Loading one where the other belongs would silently
 *  reconcile a file with itself. */
function Slot({ title, note, accept, hint, busy, drag, setDrag, onFiles, children }: {
  title: string;
  note: string;
  accept: string;
  hint: string;
  busy: boolean;
  drag: boolean;
  setDrag: (v: boolean) => void;
  onFiles: (f: FileList | null) => void;
  children?: React.ReactNode;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="srcslot">
      <div className="srcslot-head">
        <b>{title}</b>
        <span className="sub">{note}</span>
      </div>
      <div
        className={"dropzone" + (drag ? " over" : "")}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files); }}
        onClick={() => ref.current?.click()}
      >
        <input ref={ref} type="file" accept={accept} style={{ display: "none" }}
               onChange={(e) => onFiles(e.target.files)} />
        <b>{busy ? "Reading…" : "Drop the spreadsheet here"}</b>
        <span className="sub">{hint}</span>
      </div>
      {children}
    </div>
  );
}

export default function SourceData({ id, rev, onChanged }: {
  id: string;
  rev?: number;
  onChanged: () => void;
}) {
  const [loop, setLoop] = useState<LoopState | null>(null);
  const [z, setZ] = useState<ZatcaState | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [dragA, setDragA] = useState(false);
  const [dragB, setDragB] = useState(false);

  const load = useCallback(() => {
    getLoop(id).then(setLoop).catch(() => {});
    getZatca(id).then(setZ).catch(() => {});
  }, [id]);
  useEffect(load, [load, rev]);

  const sendListing = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy("listing");
    setErr("");
    try {
      for (const f of Array.from(files)) await uploadDocument(id, f);
      load();
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed.");
    } finally { setBusy(""); }
  };

  const sendZatca = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy("zatca");
    setErr("");
    try {
      setZ(await uploadZatca(id, files[0]));
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed.");
    } finally { setBusy(""); }
  };

  const docs = (loop?.documents ?? []).filter((d) => !d.superseded);
  const rows = docs.reduce((n, d) => n + (d.row_count || 0), 0);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Source data</h2>
        <div className="chips">
          <span className={"pill " + (docs.length ? "pri-low" : "pri-medium")}>
            {docs.length ? `${docs.length} file${docs.length === 1 ? "" : "s"} · ${rows} rows` : "nothing loaded"}
          </span>
          {z?.dataset && <span className="pill status">ZATCA records loaded</span>}
        </div>
      </div>

      <div className="panel-body">
        {err && <div className="callout warn">{err}</div>}

        <div className="sourcegrid">
          <Slot
            title="The taxpayer's invoice listing"
            note="the population — every rule is applied to these rows"
            accept=".xlsx,.xlsm,.csv,.tsv"
            hint=".xlsx, .xlsm, .csv — read into columns and rows on arrival"
            busy={busy === "listing"} drag={dragA} setDrag={setDragA}
            onFiles={sendListing}
          >
            {docs.length ? (
              <div className="doclist">
                {docs.map((d) => (
                  <div className="docrow" key={d.id}>
                    <b>{d.filename}</b>
                    <span className="sub">
                      {d.row_count} rows · {d.columns.length} columns
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="detail-note" style={{ margin: "10px 0 0" }}>
                Nothing loaded, so the investigation falls back to the e-invoice feed. A file
                dropped here is filed on the open enquiry, exactly as if it had arrived in
                Taxpayer Correspondence.
              </p>
            )}
          </Slot>

          <Slot
            title="ZATCA's own invoice records"
            note="optional — what the listing is matched against"
            accept=".xlsx,.xlsm,.csv,.tsv"
            hint="one row per invoice, as the Authority holds it"
            busy={busy === "zatca"} drag={dragB} setDrag={setDragB}
            onFiles={sendZatca}
          >
            {z?.dataset ? (
              <div className="doclist">
                <div className="docrow">
                  <b>{z.dataset.filename}</b>
                  <span className="sub">
                    {z.zatca_count} invoices
                    {z.comparable ? ` · ${z.matched_count} matched` : " · nothing to match against"}
                  </span>
                  <button className="linklike danger" disabled={!!busy}
                          onClick={() => removeZatca(id).then((s) => { setZ(s); onChanged(); })}>
                    remove
                  </button>
                </div>
              </div>
            ) : (
              <p className="detail-note" style={{ margin: "10px 0 0" }}>
                Without it the matching is simply not run. One side is not a comparison, so
                nothing is reported as unmatched.
              </p>
            )}
          </Slot>
        </div>
      </div>
    </div>
  );
}
