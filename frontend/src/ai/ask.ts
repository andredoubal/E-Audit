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

/** Open the docked case assistant, from anywhere. */
const OPEN_ASSISTANT = "eaudit:open-assistant";

export function openAssistant(): void {
  window.dispatchEvent(new CustomEvent(OPEN_ASSISTANT));
}

export function onOpenAssistant(handler: () => void): () => void {
  window.addEventListener(OPEN_ASSISTANT, handler);
  return () => window.removeEventListener(OPEN_ASSISTANT, handler);
}

/** Open the case's standing instructions, from the sidebar. */
const OPEN_INSTRUCTIONS = "eaudit:open-instructions";

export function openInstructions(): void {
  window.dispatchEvent(new CustomEvent(OPEN_INSTRUCTIONS));
}

export function onOpenInstructions(handler: () => void): () => void {
  window.addEventListener(OPEN_INSTRUCTIONS, handler);
  return () => window.removeEventListener(OPEN_INSTRUCTIONS, handler);
}
