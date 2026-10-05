import { AppRoutes } from "./routes";
import { SessionProvider } from "./session";

export { AppShell } from "./AppShell";

/** The whole app: sign-in state from GET /api/me, then the routes (Story 1.6). */
export function App() {
  return (
    <SessionProvider>
      <AppRoutes />
    </SessionProvider>
  );
}
