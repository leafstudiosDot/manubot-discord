import { Link } from "react-router-dom";

function NotFound() {
  return (
    <section className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
      <h2 className="mt-0 text-xl font-semibold text-amber-700">Page Not Found</h2>
      <p className="mb-4 text-sm text-amber-700">
        The page you are trying to access does not exist.
      </p>
      <Link
        to="/"
        className="inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
      >
        Back to Dashboard
      </Link>
    </section>
  );
}

export default NotFound;
