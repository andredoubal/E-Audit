import { Routes, Route, Navigate, useParams } from "react-router-dom";
import Layout from "./components/Layout";
import Overview from "./pages/Overview";
import Rules from "./pages/Rules";
import Investigation from "./pages/Investigation";
import Dossier from "./pages/Dossier";
import Correspondence from "./pages/Correspondence";
import Report from "./pages/Report";
import NewCase from "./pages/NewCase";

/** The old four-tab URLs still work — a link in someone's notes should not rot because the app was reorganised. */
function Moved({ to }: { to: string }) {
  const { id } = useParams();
  return <Navigate to={`/cases/${id}${to}`} replace />;
}

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/cases/new" element={<NewCase />} />

        <Route path="/cases/:id/correspondence" element={<Correspondence />} />
        <Route path="/cases/:id/investigation" element={<Investigation />} />
        <Route path="/cases/:id/report" element={<Report />} />

        <Route path="/cases/:id/dossier" element={<Dossier />} />
        <Route path="/cases/:id" element={<Moved to="/correspondence" />} />

        <Route path="/cases/:id/intake" element={<Moved to="/correspondence" />} />
        <Route path="/cases/:id/casework" element={<Moved to="/correspondence" />} />
        <Route path="/cases/:id/reconciliation" element={<Moved to="/investigation" />} />

        <Route path="/rules" element={<Rules />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
