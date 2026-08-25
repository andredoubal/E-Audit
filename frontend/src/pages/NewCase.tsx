import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createCase, type NewCaseIn } from "../api";

// Mirrors backend/app/seed/corpus.py's generation conventions, so an auto-generated case
// looks like the rest of the demo data rather than inventing its own style.
const SECTORS: { sector: string; isic: string; description: string }[] = [
  { sector: "Wholesale trade", isic: "4690", description: "Non-specialised wholesale trade" },
  { sector: "Retail trade", isic: "4711", description: "Retail sale in non-specialised stores" },
  { sector: "Construction", isic: "4100", description: "Construction of buildings" },
  { sector: "Transport & logistics", isic: "4923", description: "Freight transport by road" },
  { sector: "Manufacturing", isic: "2011", description: "Manufacture of basic chemicals" },
  { sector: "Food retail", isic: "4721", description: "Retail sale of food in specialised stores" },
  { sector: "Professional services", isic: "6920", description: "Accounting, bookkeeping and auditing" },
  { sector: "Medical equipment", isic: "4649", description: "Wholesale of other household goods" },
  { sector: "Telecommunications", isic: "6110", description: "Wired telecommunications activities" },
  { sector: "Hospitality", isic: "5610", description: "Restaurants and mobile food service activities" },
  { sector: "Real estate", isic: "6810", description: "Real estate activities with own or leased property" },
  { sector: "Information technology", isic: "6201", description: "Computer programming activities" },
];
const NAME_A = ["Al-Rajhi", "Al-Nahda", "Al-Waha", "Riyadh", "Jeddah", "Dammam", "Qassim", "Asir",
  "Madinah", "Taif", "Khobar", "Buraidah", "Najran", "Jazan", "Sakaka", "Arar",
  "Al-Bahah", "Unaizah", "Hafar", "Yanbu", "Rabigh", "Dhahran"];
const NAME_B = ["Trading", "Industrial", "Commercial", "Development", "Services", "Enterprises",
  "Group", "Holding", "Contracting", "Supplies", "Systems", "Solutions"];
const NAME_C = ["Co.", "Est.", "LLC", "Company", "Group"];
const CREATION_REASONS = ["Risk Engine", "Whistleblowers report", "Report from OGAs",
  "Internal referral", "Other"];
const NAMES = ["Fahad Al-Otaibi", "Noura Al-Harbi", "Khalid Al-Ghamdi", "Sara Al-Dosari",
  "Abdullah Al-Qahtani", "Maha Al-Shehri"];

const pick = <T,>(arr: T[]) => arr[Math.floor(Math.random() * arr.length)];
const digits = (n: number) => Array.from({ length: n }, () => Math.floor(Math.random() * 10)).join("");
const todayISO = () => new Date().toISOString().slice(0, 10);
const quarterEnd = (fromISO: string) => {
  const d = new Date(fromISO);
  d.setMonth(d.getMonth() + 3);
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
};

interface Activity { isic: string; description: string; primary: boolean }

export default function NewCase() {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [caseId, setCaseId] = useState("");
  const [name, setName] = useState("");
  const [vat, setVat] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [address, setAddress] = useState("");
  const [activities, setActivities] = useState<Activity[]>([]);
  const [sectorPick, setSectorPick] = useState(SECTORS[0].sector);

  const [creationDate, setCreationDate] = useState(todayISO());
  const [creationReason, setCreationReason] = useState("");
  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");

  const [manager, setManager] = useState("");
  const [supervisor, setSupervisor] = useState("");
  const [officer, setOfficer] = useState("");

  const [auditedBefore, setAuditedBefore] = useState(false);
  const [auditedBeforeNote, setAuditedBeforeNote] = useState("");

  const addActivity = () => {
    const s = SECTORS.find((x) => x.sector === sectorPick);
    if (!s || activities.some((a) => a.isic === s.isic)) return;
    setActivities((prev) => [...prev, { isic: s.isic, description: s.description, primary: prev.length === 0 }]);
  };
  const removeActivity = (isic: string) =>
    setActivities((prev) => prev.filter((a) => a.isic !== isic));
  const makePrimary = (isic: string) =>
    setActivities((prev) => prev.map((a) => ({ ...a, primary: a.isic === isic })));

  const autoGenerate = () => {
    const s = pick(SECTORS);
    setName(`${pick(NAME_A)} ${pick(NAME_B)} ${pick(NAME_C)}`);
    setVat(`300${digits(4)}00${digits(1)}0003`);
    setPhone(`+9665${digits(8)}`);
    setEmail("finance@example-taxpayer.sa");
    setAddress(`${pick(NAME_A)} District, ${pick(["Riyadh", "Jeddah", "Dammam"])}, Saudi Arabia`);
    setActivities([{ isic: s.isic, description: s.description, primary: true }]);
    setSectorPick(s.sector);

    const from = "2025-01-01";
    setPeriodFrom(from);
    setPeriodTo(quarterEnd(from));
    setCreationDate(todayISO());
    setCreationReason(pick(CREATION_REASONS));

    setManager(pick(NAMES));
    setSupervisor(pick(NAMES));
    setOfficer(pick(NAMES));

    setAuditedBefore(Math.random() < 0.3);
    setAuditedBeforeNote("");
    setCaseId("");
    setErr(null);
  };

  const canSubmit = name.trim() && vat.trim() && periodFrom && periodTo && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setErr(null);
    try {
      const body: NewCaseIn = {
        case_id: caseId.trim(),
        period_from: periodFrom,
        period_to: periodTo,
        creation_date: creationDate,
        creation_reason: creationReason,
        audit_manager: manager.trim(),
        audit_supervisor: supervisor.trim(),
        audit_officer: officer.trim(),
        taxpayer: {
          name: name.trim(),
          vat_registration_number: vat.trim(),
          ind_sector: activities.find((a) => a.primary)?.description || activities[0]?.description || "",
          economic_activities: activities,
          contact_phone: phone.trim(),
          contact_email: email.trim(),
          contact_address: address.trim(),
          audited_before: auditedBefore,
          audited_before_note: auditedBeforeNote.trim(),
        },
      };
      const created = await createCase(body);
      nav(`/cases/${created.case_id}`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">No live integration — this is how a case gets in</p>
          <h1>Add case</h1>
        </div>
        <button className="linklike" onClick={autoGenerate} disabled={busy}>
          ⚡ Auto-generate
        </button>
      </div>

      {err && <div className="notice err">{err}</div>}

      <div className="panel">
        <div className="panel-head">
          <h2>Taxpayer information</h2>
        </div>
        <div className="panel-body">
          <div className="resp-form">
            <div className="resp-row">
              <input placeholder="Taxpayer name" value={name} onChange={(e) => setName(e.target.value)} />
              <input placeholder="Taxpayer TIN (VAT registration number)" value={vat} onChange={(e) => setVat(e.target.value)} />
            </div>
            <div className="resp-row">
              <input placeholder="Contact phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
              <input placeholder="Contact e-mail" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <input placeholder="Contact address" value={address} onChange={(e) => setAddress(e.target.value)} />

            <div className="formula">
              <span className="k">Sectors / economic activities</span>
              <div className="resp-row">
                <select value={sectorPick} onChange={(e) => setSectorPick(e.target.value)}>
                  {SECTORS.map((s) => (
                    <option key={s.isic} value={s.sector}>{s.sector} — {s.isic}</option>
                  ))}
                </select>
                <button className="btn-ghost" type="button" onClick={addActivity}>+ Add</button>
              </div>
              {activities.length > 0 && (
                <div className="resp-list">
                  {activities.map((a) => (
                    <div className="resp-item" key={a.isic}>
                      <div>{a.primary && "★ "}{a.description} <span className="sub mono">{a.isic}</span></div>
                      <div style={{ display: "flex", gap: 12 }}>
                        {!a.primary && (
                          <button className="linklike" type="button" onClick={() => makePrimary(a.isic)}>make primary</button>
                        )}
                        <button className="linklike danger" type="button" onClick={() => removeActivity(a.isic)}>remove</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="callout">
              <label className="switch">
                <input type="checkbox" checked={auditedBefore} onChange={(e) => setAuditedBefore(e.target.checked)} />
                <span className="switch-track"><span className="switch-thumb" /></span>
                <span className="switch-label">Has this taxpayer been audited before?</span>
              </label>
              {auditedBefore && (
                <input
                  style={{ marginTop: 9 }}
                  placeholder="Note on the prior audit (outcome, period, anything relevant)"
                  value={auditedBeforeNote}
                  onChange={(e) => setAuditedBeforeNote(e.target.value)}
                />
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Audit case information</h2>
        </div>
        <div className="panel-body">
          <div className="resp-form">
            <div className="resp-row">
              <input placeholder="Audit Case ID (leave blank to auto-generate)" value={caseId} onChange={(e) => setCaseId(e.target.value)} />
              <input type="date" value={creationDate} onChange={(e) => setCreationDate(e.target.value)} />
            </div>
            <div className="resp-row">
              <select value={creationReason} onChange={(e) => setCreationReason(e.target.value)}>
                <option value="">Case Creation Reason…</option>
                {CREATION_REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div className="formula">
              <span className="k">Audit Case Tax Period — from / to</span>
              <div className="resp-row">
                <input type="date" value={periodFrom} onChange={(e) => setPeriodFrom(e.target.value)} />
                <input type="date" value={periodTo} onChange={(e) => setPeriodTo(e.target.value)} />
              </div>
            </div>
            <div className="kv">
              <div><span className="k">Tax type</span><span className="v">VAT</span></div>
              <div><span className="k">Place of conduct of Audit</span><span className="v">Desk audit</span></div>
              <div><span className="k">Address of Audit location</span><span className="v">Not applicable</span></div>
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Assigned audit team information</h2>
        </div>
        <div className="panel-body">
          <div className="resp-row">
            <input placeholder="Audit Manager" value={manager} onChange={(e) => setManager(e.target.value)} />
            <input placeholder="Audit Supervisor" value={supervisor} onChange={(e) => setSupervisor(e.target.value)} />
            <input placeholder="Audit Officer" value={officer} onChange={(e) => setOfficer(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="resp-actions">
        <button className="btn" disabled={!canSubmit} onClick={submit}>
          {busy ? "Creating…" : "Create case"}
        </button>
        <button className="linklike" onClick={() => nav("/")}>cancel</button>
      </div>
    </div>
  );
}
