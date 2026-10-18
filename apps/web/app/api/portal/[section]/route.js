import { readPortal } from "../../../../lib/portal";
export const dynamic = "force-dynamic";
export async function GET(_request, { params }) {
  const { section } = await params;
  return readPortal(section);
}
