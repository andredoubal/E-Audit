import { useState } from "react";
import { askRegulatoryQuery, type RegQueryResult } from "../api";
import { useRegulatoryAnswer } from "../ai/useStream";
import RegulatoryCitationsPanel from "../components/RegulatoryCitationsPanel";
import VerifyBadge from "../components/VerifyBadge";

const EXAMPLES = [
  "What does Article 49 say about adjusting output tax?",
  "What conditions apply to a credit note adjustment?",
  "What are the time limits for adjustments under Article 49?",
];

/** Mode A: conversational regulatory Q&A. Retrieval (citations panel) is deterministic and
 *  renders immediately with zero API key; the explanation below it is the one Claude-authored
 *  piece, cite-or-drop verified before display, with a deterministic fallback (a plain
 *  citation list) when unverified or no key is configured. */
export default function Regulatory() {
  const [question, setQuestion] = useState("");
  const [taxPeriod, setTaxPeriod] = useState("");
  const [result, setResult] = useState<RegQueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const answer = useRegulatoryAnswer(result?.trace_id);

  const ask = async (q: string) => {
    if (!q.trim()) return;
    setLoading(true);
    setErr(null);
    setResult(null);
    try {
      const r = await askRegulatoryQuery(q, taxPeriod || undefined);
      setResult(r);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Regulatory knowledge</p>
          <h1>Ask the VAT Implementing Regulations</h1>
        </div>
      </div>

      <div className="panel">
        <div className="panel-body">
          <div className="controls" style={{ alignItems: "flex-start" }}>
            <div className="search" style={{ flex: 1 }}>
              <input
                placeholder="e.g. What does Article 49 say about adjusting output tax?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && ask(question)}
              />
            </div>
            <input
              type="date"
              value={taxPeriod}
              onChange={(e) => setTaxPeriod(e.target.value)}
              title="Optional — resolve the legal version applicable to this tax period"
              style={{ width: 160 }}
            />
            <button className="btn" onClick={() => ask(question)} disabled={loading}>
              {loading ? "Searching…" : "Ask"}
            </button>
          </div>
          <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                className="chip"
                onClick={() => {
                  setQuestion(ex);
                  ask(ex);
                }}
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      </div>

      {err && (
        <div className="panel">
          <div className="notice err">{err}</div>
        </div>
      )}

      {result && (
        <>
          <RegulatoryCitationsPanel units={result.cited_units} />

          <div className="panel">
            <div className="panel-head">
              <div className="ai-h">
                <h2>Explanation</h2>
              </div>
              <VerifyBadge source={answer.source} />
            </div>
            <div className="panel-body">
              <p style={{ whiteSpace: "pre-wrap" }} dir="auto">
                {answer.text || (answer.streaming ? "Drafting…" : "")}
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
