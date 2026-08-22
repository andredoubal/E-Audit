/** A way to open the case assistant already knowing what is being asked about.
 *
 *  The alternative — a Challenge button that opens a blank chat saying "what do you want to
 *  challenge?" — makes the auditor retype what they are already looking at, and gives the
 *  assistant no idea which of forty rows is in dispute. So the item hands over its own context,
 *  and the assistant opens with the question already written.
 *
 *  A tiny event bus rather than a context provider: `CaseAssistant` is mounted once per case,
 *  far from the rows that want to talk to it, and threading a callback down through four panels
 *  to reach it would be more machinery than the one line this needs.
 */
const EVENT = "eaudit:ask-assistant";

export function askAbout(question: string): void {
  window.dispatchEvent(new CustomEvent(EVENT, { detail: question }));
}

export function onAsk(handler: (question: string) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<string>).detail);
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
