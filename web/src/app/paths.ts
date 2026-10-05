// The app's URL paths, shared by the routes and the header.
export const paths = {
  welcome: "/",
  drafts: "/proposals",
  submitted: "/proposals/submitted",
  proposal: "/proposals/:id",
} as const;

/** One proposal's workspace URL (Story 1.8). */
export function proposalPath(id: string): string {
  return `/proposals/${id}`;
}
