import type { ReactNode } from "react";
import { Link, Navigate, Outlet, Route, Routes, useParams } from "react-router";
import { AvatarMenu } from "../components/AvatarMenu";
import { ProposalsPage } from "../pages/ProposalsPage";
import { Workspace } from "../pages/workspace/Workspace";
import { WelcomePage } from "../pages/WelcomePage";
import { strings } from "../strings";
import { AppShell } from "./AppShell";
import { BreadcrumbProvider, useBreadcrumbLabel } from "./breadcrumb";
import { paths } from "./paths";
import { useSession } from "./session";

function DraftsPage() {
  return <ProposalsPage status="draft" />;
}

function SubmittedPage() {
  return <ProposalsPage status="submitted" />;
}

/**
 * The proposal workspace route (Story 1.9). `Workspace` sets the breadcrumb itself, from the
 * fetched draft's own `display_name`, once loaded -- covering a New-proposal navigation, a
 * Drafts-list row, a direct URL and a reload alike (spec assumption "Breadcrumb on open"), so
 * unlike Story 1.8's placeholder this reads nothing from `location.state`.
 */
function WorkspacePage() {
  const { id } = useParams();
  if (!id) return <Navigate to={paths.drafts} replace />;
  return <Workspace draftId={id} />;
}

/** `/`: the Welcome page when signed out; a signed-in user goes straight to Drafts. */
function WelcomeRoute() {
  const session = useSession();
  if (session.status === "unknown") return null;
  if (session.status === "signed-in") {
    return <Navigate to={paths.drafts} replace />;
  }
  return <WelcomePage />;
}

/** The header's breadcrumb, "Drafts / <name>", where "Drafts" links back to the list (Story 1.8). */
function Breadcrumb({ label }: { label: string }) {
  return (
    <p className="breadcrumb">
      <Link to={paths.drafts} className="breadcrumb__link">
        {strings.proposals.drafts}
      </Link>{" "}
      / <span className="breadcrumb__current">{label}</span>
    </p>
  );
}

/** Reads the breadcrumb a page below it set, and renders the shell around the current route. */
function SignedInShell({ user }: { user: ReactNode }) {
  const label = useBreadcrumbLabel();
  return (
    <AppShell
      header={label ? <Breadcrumb label={label} /> : undefined}
      user={user}
    >
      <Outlet />
    </AppShell>
  );
}

/** Every page after Welcome: signed-out visitors go to Welcome; the header shows her avatar. */
function SignedInLayout() {
  const session = useSession();
  if (session.status === "unknown") return null;
  if (session.status === "signed-out") {
    return <Navigate to={paths.welcome} replace />;
  }
  return (
    <BreadcrumbProvider>
      <SignedInShell user={<AvatarMenu me={session.me} />} />
    </BreadcrumbProvider>
  );
}

/**
 * The app's routes (Story 1.6 guards): sign-in state comes only from GET /api/me, and nothing
 * renders until it answers. Any unknown path goes to Drafts, or to Welcome when signed out.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path={paths.welcome} element={<WelcomeRoute />} />
      <Route element={<SignedInLayout />}>
        <Route path={paths.drafts} element={<DraftsPage />} />
        <Route path={paths.submitted} element={<SubmittedPage />} />
        <Route path={paths.proposal} element={<WorkspacePage />} />
        <Route path="*" element={<Navigate to={paths.drafts} replace />} />
      </Route>
    </Routes>
  );
}
