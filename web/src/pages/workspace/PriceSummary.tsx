// Story 2.3: the read-only price summary below the question table on pages 2 and 3
// (epic-2-context.md "Price summary on pages 2 and 3"), built only from `quote` -- the web app
// never computes a price itself (coding-style.md rule 16).
import type { Quote } from "../../api/client";
import { strings } from "../../strings";
import { formatRm } from "./money";

export function PriceSummary({ quote }: { quote: Quote }) {
  if (quote === null) {
    return (
      <p className="ws-price-summary ws-price-summary--placeholder">
        {strings.priceSummary.placeholder}
      </p>
    );
  }
  return (
    <div className="ws-price-summary">
      <ul className="ws-price-summary__lines">
        {quote.lines.map((line) => (
          <li key={line.item}>
            {strings.priceSummary.line(
              line.item,
              formatRm(line.monthly),
              formatRm(line.yearly),
            )}
          </li>
        ))}
      </ul>
      <p className="ws-price-summary__total">
        {strings.priceSummary.total(
          formatRm(quote.monthly),
          formatRm(quote.yearly),
        )}
      </p>
    </div>
  );
}
