import { useEffect, useState } from "react";
import { getStepEmails, type StepEmail } from "../api";
import LetterDraft from "./LetterDraft";

/** The drafts that go back out: the chase, and the verdict. */
export default function StepEmails({ id, rev, only }: {
  id?: string;
  rev?: number;
  /** Which drafts to show. */
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
