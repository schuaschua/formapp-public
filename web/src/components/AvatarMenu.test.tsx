import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { strings } from "../strings";
import { AvatarMenu, SIGN_OUT_URL } from "./AvatarMenu";

const ALICE = { name: "Alice Synthetic", firstName: "Alice" };

function renderMenu(me = ALICE) {
  render(
    <>
      <AvatarMenu me={me} />
      <button type="button">elsewhere</button>
    </>,
  );
  return screen.getByRole("button", {
    name: strings.account.buttonLabel(me.firstName || me.name),
  });
}

describe("1.6 avatar menu", () => {
  it("story 1.6: shows her avatar initial and first name, menu closed", () => {
    const avatar = renderMenu();

    expect(avatar).toHaveTextContent("AAlice");
    expect(avatar.querySelector(".avatar")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(avatar).toHaveAttribute("aria-haspopup", "menu");
    expect(avatar).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("story 1.6: a click opens the menu with Sign out", async () => {
    const avatar = renderMenu();

    await userEvent.click(avatar);

    expect(avatar).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu");
    expect(avatar).toHaveAttribute("aria-controls", menu.id);
    const signOut = screen.getByRole("menuitem", { name: "Sign out" });
    expect(signOut).toHaveAttribute("href", SIGN_OUT_URL);
    expect(SIGN_OUT_URL).toBe("/.auth/logout?post_logout_redirect_uri=/");
    expect(signOut).toHaveFocus();
  });

  it.each(["{Enter}", " "])(
    "story 1.6: %j on the avatar opens the menu",
    async (key) => {
      const avatar = renderMenu();
      avatar.focus();

      await userEvent.keyboard(key);

      expect(screen.getByRole("menuitem", { name: "Sign out" })).toHaveFocus();
    },
  );

  it("story 1.6: Escape closes the menu and returns focus to the avatar", async () => {
    const avatar = renderMenu();
    await userEvent.click(avatar);

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(avatar).toHaveFocus();
    expect(avatar).toHaveAttribute("aria-expanded", "false");
  });

  it("story 1.6: a second click, or focus moving away, closes the menu", async () => {
    const avatar = renderMenu();
    await userEvent.click(avatar);
    await userEvent.click(avatar);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await userEvent.click(avatar);
    await userEvent.click(screen.getByRole("button", { name: "elsewhere" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("story 1.6: pressing the avatar doesn't move focus, so a second click closes the menu", async () => {
    const avatar = renderMenu();
    await userEvent.click(avatar);
    const signOut = screen.getByRole("menuitem", { name: "Sign out" });

    // A mouse press on the avatar is cancelled, so the open menu keeps focus until the click.
    const press = new MouseEvent("mousedown", {
      bubbles: true,
      cancelable: true,
    });
    avatar.dispatchEvent(press);
    expect(press.defaultPrevented).toBe(true);
    expect(signOut).toHaveFocus();

    await userEvent.click(avatar);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("story 1.6: Escape with the menu closed does nothing", async () => {
    const avatar = renderMenu();
    avatar.focus();

    await userEvent.keyboard("{Escape}");

    expect(avatar).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("story 1.6: without a first name, the display name is shown", () => {
    const avatar = renderMenu({ name: "ally@example.test", firstName: "" });

    expect(avatar).toHaveTextContent("Aally@example.test");
  });
});
