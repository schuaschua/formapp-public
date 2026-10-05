import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation } from "react-router";
import { getMe, setUnauthorizedHandler, type Me } from "../api/client";

// Story 1.6: sign-in state comes only from GET /api/me. "unknown" lasts until the first answer, and
// pages render nothing meanwhile (no spinner, and no flash of the wrong page).
export type Session =
  | { status: "unknown" }
  | { status: "signed-out" }
  | { status: "signed-in"; me: Me };

const SessionContext = createContext<Session>({ status: "unknown" });

/**
 * Asks the api who is signed in when the app loads, and again on every navigation, so an expired
 * session sends her back to the Welcome page. A failed first check counts as signed out; a failed
 * later check keeps what we knew, so a passing outage doesn't sign her out.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const [session, setSession] = useState<Session>({ status: "unknown" });
  const known = useRef(false);

  // Story 1.10: any 401 from any /api call (autosave, chat, ...) pushes signed-out at once, so a
  // failed call sends her to Welcome without waiting for a route change to re-check GET /api/me.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      known.current = true;
      setSession({ status: "signed-out" });
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    let current = true;
    getMe().then(
      (me) => {
        if (!current) return;
        known.current = true;
        setSession(me ? { status: "signed-in", me } : { status: "signed-out" });
      },
      () => {
        if (!current || known.current) return;
        known.current = true;
        setSession({ status: "signed-out" });
      },
    );
    return () => {
      current = false;
    };
  }, [pathname]);

  return (
    <SessionContext.Provider value={session}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): Session {
  return useContext(SessionContext);
}
