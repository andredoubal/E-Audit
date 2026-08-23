import { useCallback, useEffect, useRef, useState } from "react";
import { getZatca, removeZatca, uploadZatca, type ZatcaState } from "../api";
import { Table } from "./Icon";

/** The one file that is uploaded *here* rather than in Taxpayer Correspondence.
 *
 *  Everything the taxpayer sent arrives on an enquiry and is managed there; the investigation
 *  reads it, and offering a second place to upload it would mean the same listing could be
 *  filed twice against two different rounds. This is the Authority's own extract — internal,
 *  optional, and answering to no request — so it has nowhere else to go.
 *
 *  Collapsed by default, because on most cases the answer is "no file", and a dropzone open
 *  above the findings implies the investigation is waiting for something. It is not: with no
 *  dataset the matching is simply not run, and nothing is reported as unmatched. */
export default function ZatcaSource({ id, rev, onChanged }: {
  id: string;
  rev?: number;
  onChanged: () => void;
}) {
  const [d, setD] = useState<ZatcaState | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const ref = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    getZatca(id).then(setD).catch(() => {});
  }, [id]);
  useEffect(load, [load, rev]);

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setErr("");
    try {
      setD(await uploadZatca(id, files[0]));
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read that file.");
    } finally {
      setBusy(false);
    }
  };

  const unload = async () => {
    setBusy(true);
    try {
      setD(await removeZatca(id));
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const ds = d?.dataset;

  return (
    <section className={"zsrc" + (open ? " on" : "")}>
      <button className="zsrc-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="zsrc-ic"><Table /></span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "flex", alignItems: "baseline", gap: 9 }}>
            <b>ZATCA invoice records</b>
            <span className="zsrc-opt">optional</span>
          </span>
          {ds ? (
            <span className="zsrc-file" style={{ display: "block", marginTop: 4 }}>
              {ds.filename}
              {ds.uploaded_at && ` · loaded ${ds.uploaded_at.slice(0, 10)}`}
              {d?.comparable && ` · ${d.matched_count} matched`}
            </span>
          ) : (
            <span className="zsrc-none" style={{ display: "block", marginTop: 4 }}>
              None loaded — the investigation runs on the taxpayer's documents alone
            </span>
          )}
        </span>
        <span className="zsrc-mark">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="zsrc-body">
          {err && <div className="callout warn">{err}</div>}

          <div
            className={"dropzone" + (drag ? " over" : "")}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
            onClick={() => ref.current?.click()}
          >
            <input ref={ref} type="file" accept=".xlsx,.xlsm,.csv,.tsv"
                   style={{ display: "none" }}
                   onChange={(e) => send(e.target.files)} />
            <b>{busy ? "Reading…" : ds ? "Drop a file here to replace it" : "Drop the Authority's invoice extract here"}</b>
            <span>.xlsx, .xlsm, .csv — one row per invoice, as ZATCA holds it</span>
          </div>

          {ds ? (
            <div className="zsrc-meta">
              <span><span className="k">File</span>{ds.filename}</span>
              <span><span className="k">Invoices</span>{ds.row_count}</span>
              <span><span className="k">Columns</span>{ds.columns.length}</span>
              <span><span className="k">Loaded</span>{ds.uploaded_at.slice(0, 10)}</span>
              <button className="linklike danger" disabled={busy} onClick={unload}>
                remove
              </button>
            </div>
          ) : (
            <p className="detail-note" style={{ marginBottom: 0 }}>
              The taxpayer's own documents come from Correspondence and are already in use here.
              This slot is for ZATCA's internal invoice extract. Without it there is one side and
              no comparison, so no reconciliation is reported.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
