import type { ReactNode } from "react";
import "./InfoNote.css";

export type InfoNoteProps = {
  children: ReactNode;
  /** Three fading dots while something is in progress ("AI is filling in answers…", DESIGN.md
   * Components "Info note"); omitted for a note that's just a fact, like the lock-elsewhere one
   * (DESIGN.md "Other-window note"). */
  dots?: boolean;
};

/** Form-header pill that explains why the form is read-only (DESIGN.md Components "Info note",
 * `{components.info-note}`). */
export function InfoNote({ children, dots = false }: InfoNoteProps) {
  return (
    <span className="info-note" aria-live={dots ? "polite" : undefined}>
      <span className="info-note__text">{children}</span>
      {dots && (
        <span className="info-note__dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      )}
    </span>
  );
}
