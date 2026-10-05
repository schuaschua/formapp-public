import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

// The workspace sets the header's breadcrumb label while it is mounted (Story 1.8, UX-DR-breadcrumb);
// every other page leaves it unset, so the header shows the plain logo (Story 1.4).
type SetBreadcrumb = (label: string | null) => void;

const BreadcrumbContext = createContext<string | null>(null);
const SetBreadcrumbContext = createContext<SetBreadcrumb>(() => {});

export function BreadcrumbProvider({ children }: { children: ReactNode }) {
  const [label, setLabel] = useState<string | null>(null);
  return (
    <SetBreadcrumbContext.Provider value={setLabel}>
      <BreadcrumbContext.Provider value={label}>
        {children}
      </BreadcrumbContext.Provider>
    </SetBreadcrumbContext.Provider>
  );
}

/** A page calls this with its breadcrumb label; it clears again when the page unmounts. */
export function useBreadcrumb(label: string | null): void {
  const setLabel = useContext(SetBreadcrumbContext);
  useEffect(() => {
    setLabel(label);
    return () => setLabel(null);
  }, [label, setLabel]);
}

/** The current breadcrumb label, read by the shell that renders the header slot. */
export function useBreadcrumbLabel(): string | null {
  return useContext(BreadcrumbContext);
}
