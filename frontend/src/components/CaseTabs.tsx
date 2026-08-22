import CaseInstructions from "./CaseInstructions";

/** The case's standing instructions, on every module.
 *
 *  The three module links moved into the sidebar, nested under the case that is open, so the
 *  horizontal tab bar that used to be here would be a second copy of the same navigation. */
export default function CaseTabs({ id }: { id: string }) {
  return <CaseInstructions id={id} />;
}
