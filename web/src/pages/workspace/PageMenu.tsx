import { GlassCard } from "../../components/GlassCard";
import { strings } from "../../strings";
import "./PageMenu.css";

export type PageMenuPage = {
  number: number;
  title: string;
  /** The bold forest pill: the page the form card is showing right now. */
  current: boolean;
  /** Every active required question on this page has a valid answer (independent of `current`). */
  done: boolean;
  /** Story 3.1: this page has at least one unresolved Submit problem (independent of `current`). */
  problem: boolean;
};

/**
 * The workspace's page menu (Story 1.9, DESIGN.md Components "Page menu"/"Page menu rail"):
 * expanded list or a collapsed rail of numbered circles, plus the progress bar. Story 3.1 adds the
 * amber problem box/badge and the current+problem ring, after a failed Submit.
 */
export function PageMenu({
  pages,
  collapsed,
  onToggleCollapse,
  onSelectPage,
  doneCount,
  totalCount,
}: {
  pages: PageMenuPage[];
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelectPage: (page: number) => void;
  doneCount: number;
  totalCount: number;
}) {
  const toggleLabel = collapsed
    ? strings.workspace.expandMenu
    : strings.workspace.collapseMenu;
  return (
    <GlassCard
      as="nav"
      variant="menu"
      className={"page-menu" + (collapsed ? " page-menu--collapsed" : "")}
      aria-label={strings.workspace.pagesLabel}
    >
      <div className="page-menu__head">
        {!collapsed && (
          <span className="page-menu__label">
            {strings.workspace.pagesLabel}
          </span>
        )}
        <button
          type="button"
          className="page-menu__toggle"
          title={toggleLabel}
          aria-label={toggleLabel}
          onClick={onToggleCollapse}
        >
          {collapsed ? "›" : "‹"}
        </button>
      </div>
      <ul className="page-menu__list">
        {pages.map((page) => {
          // Muted only when it's neither the current page nor done (EXPERIENCE.md Component
          // Patterns "Page menu"): a done page a step below the current one keeps its ✓ and its
          // ordinary text colour, and the current page stays forest even once it's also done.
          const muted = !page.current && !page.done;
          const accessibleName =
            page.title +
            (page.done ? " ✓" : "") +
            (page.problem ? ` ${strings.workspace.answersNeeded}` : "");
          return (
            <li key={page.number}>
              <button
                type="button"
                className={
                  "page-menu__item" +
                  (page.current ? " page-menu__item--current" : "") +
                  (muted ? " page-menu__item--todo" : "") +
                  (page.problem ? " page-menu__item--problem" : "")
                }
                title={collapsed ? page.title : undefined}
                aria-label={collapsed ? accessibleName : undefined}
                aria-current={page.current ? "page" : undefined}
                onClick={() => onSelectPage(page.number)}
              >
                <span className="page-menu__number" aria-hidden="true">
                  {page.number}
                </span>
                {!collapsed && (
                  <span className="page-menu__title">{page.title}</span>
                )}
                {page.done && (
                  <span className="page-menu__check" aria-hidden="true">
                    &#x2713;
                  </span>
                )}
                {!collapsed && page.done && (
                  <span className="page-menu__sr-only">done</span>
                )}
                {page.problem && (
                  <span className="page-menu__badge" aria-hidden="true">
                    !
                  </span>
                )}
                {!collapsed && page.problem && (
                  <span className="page-menu__sr-only">
                    {strings.workspace.answersNeeded}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      {!collapsed && (
        <div className="page-menu__progress">
          <p>{strings.workspace.pagesDone(doneCount, totalCount)}</p>
          <div className="page-menu__bar">
            <span
              className="page-menu__bar-fill"
              style={{ width: `${(doneCount / totalCount) * 100}%` }}
            />
          </div>
        </div>
      )}
    </GlassCard>
  );
}
