import { useEffect, useState } from "react";
import { getStepEmails, type StepEmail } from "../api";
import LetterDraft from "./LetterDraft";

/** The drafts that go back out: the chase, and the verdict.
 *
 *  A draft appears only when its trigger exists — a chase with nothing outstanding, or a verdict
 *  before there is a position to report, would train the auditor to ignore the panel. Nothing is
 *  sent from here; every figure in a generated draft was established by the engine before Claude
 *  saw it, and an edited one is the auditor's own words, marked as such. */
export default function StepEmails({ id, rev, only }: {
  id?: string;
  rev?: number;
  /** Which drafts to show. The chase now lives beside the gaps it is written from, in step 4
   *  of the round it belongs to, so the Report tab asks for the verdict alone. */
  only?: ("follow-up" | "verdict")[];
}) {
  const [emails, setEmails] = useState<StepEmail[] | null>(null);

  useEffect(() => {
    if (!id) return;
    setEmails(null);
    getStepEmails(id).then((d) => setEmails(d.emails)).catch(() => setEmails([]));
  }, [id, rev]);

  if (!emails || !id) return null;
  const shown = emails.filter((e) => !only || only.includes(e.kind));
  if (!shown.length) return null;

  return (
    <>
      {shown.map((e) => (
        <LetterDraft key={e.kind} id={id} email={e} onSaved={setEmails} />
      ))}
    </>
  );
}
