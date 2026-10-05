import type { ComponentPropsWithoutRef, ElementType, ReactNode } from "react";
import "./GlassCard.css";

type GlassCardElement = "div" | "section" | "header" | "nav" | "aside" | "main";

export type GlassCardProps = {
  /** `menu` is the page-menu flat card; `card` (default) is the general flat card. Both are the
   *  same flat white surface (Theme E "Forest" has no glass). */
  variant?: "card" | "menu";
  as?: GlassCardElement;
  className?: string;
  children?: ReactNode;
} & Omit<ComponentPropsWithoutRef<"div">, "className" | "children" | "style">;

/** The base surface for the header, page menu, form, chat and lists (DESIGN.md Components). */
export function GlassCard({
  variant = "card",
  as = "div",
  className,
  children,
  ...rest
}: GlassCardProps) {
  const Element: ElementType = as;
  const classes = [
    "glass-card",
    variant === "menu" && "glass-card--menu",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <Element className={classes} {...rest}>
      {children}
    </Element>
  );
}
