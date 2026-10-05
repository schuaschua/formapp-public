import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { readWebFile } from "../../tests/css";
import { strings } from "../../strings";
import { PageMenu, type PageMenuPage } from "./PageMenu";

const PAGES: PageMenuPage[] = [
  { number: 1, title: "Needs", current: false, done: true, problem: false },
  { number: 2, title: "Product", current: false, done: false, problem: false },
  { number: 3, title: "Payment", current: true, done: false, problem: false },
  {
    number: 4,
    title: "Particulars",
    current: false,
    done: false,
    problem: false,
  },
  {
    number: 5,
    title: "Health & lifestyle",
    current: false,
    done: false,
    problem: false,
  },
];

function renderMenu(overrides: Partial<Parameters<typeof PageMenu>[0]> = {}) {
  const onSelectPage = vi.fn();
  const onToggleCollapse = vi.fn();
  render(
    <PageMenu
      pages={PAGES}
      collapsed={false}
      onToggleCollapse={onToggleCollapse}
      onSelectPage={onSelectPage}
      doneCount={1}
      totalCount={5}
      {...overrides}
    />,
  );
  return { onSelectPage, onToggleCollapse };
}

describe("1.9 PageMenu", () => {
  it("story 1.9: shows Pages and every numbered item with its name", () => {
    renderMenu();

    expect(screen.getByText(strings.workspace.pagesLabel)).toBeInTheDocument();
    for (const page of PAGES) {
      expect(
        screen.getByRole("button", { name: new RegExp(page.title) }),
      ).toBeInTheDocument();
    }
  });

  it("story 1.9: the current page is a bold pill with aria-current", () => {
    renderMenu();

    const current = screen.getByRole("button", { name: /Payment/ });
    expect(current).toHaveClass("page-menu__item--current");
    expect(current).toHaveAttribute("aria-current", "page");
    const other = screen.getByRole("button", { name: /Needs/ });
    expect(other).not.toHaveAttribute("aria-current");
  });

  it("story 1.9: a done page shows a forest-accent check, current or not", () => {
    renderMenu();

    const done = screen.getByRole("button", { name: /Needs/ });
    expect(done.querySelector(".page-menu__check")).not.toBeNull();
    const notDone = screen.getByRole("button", { name: /Payment/ });
    expect(notDone.querySelector(".page-menu__check")).toBeNull();
  });

  it("story 1.9: a page that is neither current nor done is muted", () => {
    renderMenu();

    expect(screen.getByRole("button", { name: /Product/ })).toHaveClass(
      "page-menu__item--todo",
    );
    // Done, but not current: normal text, not muted.
    expect(screen.getByRole("button", { name: /Needs/ })).not.toHaveClass(
      "page-menu__item--todo",
    );
    // Current, but not done: normal (forest), not muted.
    expect(screen.getByRole("button", { name: /Payment/ })).not.toHaveClass(
      "page-menu__item--todo",
    );
  });

  it("story 1.9: clicking a page item selects that page", async () => {
    const { onSelectPage } = renderMenu();

    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    expect(onSelectPage).toHaveBeenCalledWith(4);
  });

  it("story 1.9: pressing Enter on a focused page item selects that page", async () => {
    const { onSelectPage } = renderMenu();

    screen.getByRole("button", { name: /Health & lifestyle/ }).focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelectPage).toHaveBeenCalledWith(5);
  });

  it("story 1.9: the toggle collapses and expands the menu, with the right tooltip", async () => {
    const { onToggleCollapse } = renderMenu({ collapsed: false });

    const toggle = screen.getByRole("button", {
      name: strings.workspace.collapseMenu,
    });
    await userEvent.click(toggle);
    expect(onToggleCollapse).toHaveBeenCalledOnce();
  });

  it("story 1.9: collapsed, the menu is a rail of numbers with page names as tooltips", () => {
    renderMenu({ collapsed: true });

    expect(
      screen.getByRole("button", { name: strings.workspace.expandMenu }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(strings.workspace.pagesLabel),
    ).not.toBeInTheDocument();
    // Titles aren't shown as text, but stay as each item's accessible name/tooltip.
    expect(screen.queryByText("Payment")).not.toBeInTheDocument();
    const current = screen.getByRole("button", { name: "Payment" });
    expect(current).toHaveAttribute("title", "Payment");
    // A done page's tooltip says so too (accessible name, not colour alone).
    const done = screen.getByRole("button", { name: /Needs.*✓/ });
    expect(done).toBeInTheDocument();
    // No progress bar in the rail (DESIGN.md Components "Page menu rail").
    expect(
      screen.queryByText(strings.workspace.pagesDone(1, 5)),
    ).not.toBeInTheDocument();
  });

  it("story 1.9: the progress bar reads N of 5 pages done and fills proportionally", () => {
    renderMenu({ doneCount: 2, totalCount: 5 });

    expect(screen.getByText("2 of 5 pages done")).toBeInTheDocument();
    const fill = document.querySelector(".page-menu__bar-fill") as HTMLElement;
    expect(fill.style.width).toBe("40%");
  });

  it("story 1.9: the menu drops to the rail on its own at the 200% zoom breakpoint", () => {
    const css = readWebFile("src/pages/workspace/PageMenu.css");
    expect(css).toMatch(/@media \(max-width: 900px\)/);
    const mediaBlock = /@media \(max-width: 900px\)\s*\{([\s\S]*)\}\s*$/.exec(
      css,
    )?.[1];
    expect(mediaBlock).toContain("--page-menu-rail-width");
    expect(mediaBlock).toContain("page-menu__label");
  });

  it("story 3.1: a problem page gets the amber box, a ! badge, and 'Answers needed' in its name", () => {
    renderMenu({
      pages: PAGES.map((page) =>
        page.number === 2 ? { ...page, problem: true } : page,
      ),
    });

    const problemPage = screen.getByRole("button", { name: /Product/ });
    expect(problemPage).toHaveClass("page-menu__item--problem");
    expect(problemPage.querySelector(".page-menu__badge")).not.toBeNull();
    expect(problemPage).toHaveTextContent(strings.workspace.answersNeeded);
    // A page with no problem gets neither.
    const cleanPage = screen.getByRole("button", { name: /Particulars/ });
    expect(cleanPage).not.toHaveClass("page-menu__item--problem");
    expect(cleanPage.querySelector(".page-menu__badge")).toBeNull();
  });

  it("story 3.1: the current page keeps its problem box and badge too", () => {
    renderMenu({
      pages: PAGES.map((page) =>
        page.number === 3 ? { ...page, problem: true } : page,
      ),
    });

    const current = screen.getByRole("button", { name: /Payment/ });
    expect(current).toHaveClass("page-menu__item--current");
    expect(current).toHaveClass("page-menu__item--problem");
    expect(current.querySelector(".page-menu__badge")).not.toBeNull();
  });

  it("story 3.1: collapsed, a problem page's tooltip says so and shows the amber dot", () => {
    renderMenu({
      collapsed: true,
      pages: PAGES.map((page) =>
        page.number === 2 ? { ...page, problem: true } : page,
      ),
    });

    const problemPage = screen.getByRole("button", {
      name: `Product ${strings.workspace.answersNeeded}`,
    });
    expect(problemPage).toHaveAttribute("title", "Product");
    expect(problemPage.querySelector(".page-menu__badge")).not.toBeNull();
  });
});
