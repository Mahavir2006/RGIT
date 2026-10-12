import { Routes, Route, Navigate } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';
import Shell from './lib/Shell.jsx';
import { useApp } from './lib/store.jsx';
import Login from './routes/Login.jsx';
import Overview from './routes/Overview.jsx';
import Operations from './routes/Operations.jsx';
import IncidentList from './routes/IncidentList.jsx';
import IncidentDetail from './routes/IncidentDetail.jsx';
import Evidence from './routes/Evidence.jsx';
import Cascade from './routes/Cascade.jsx';
import Response from './routes/Response.jsx';
import Events from './routes/Events.jsx';
import Sources from './routes/Sources.jsx';
import Settings from './routes/Settings.jsx';
import Kitchen from './routes/Kitchen.jsx';
import Graph from './routes/Graph.jsx';

export default function App() {
  const { signedIn } = useApp();
  if (!signedIn) return <Login />;

  return (
    <Shell>
      <AnimatePresence mode="wait">
        <Routes>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          <Route path="/login" element={<Login />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/operations" element={<Operations />} />
          <Route path="/incidents" element={<IncidentList />} />
          <Route path="/incidents/:incidentId" element={<IncidentDetail />} />
          <Route path="/incidents/:incidentId/evidence" element={<Evidence />} />
          <Route path="/incidents/:incidentId/graph" element={<Graph />} />
          <Route path="/graph" element={<Graph />} />
          <Route path="/graph/:incidentId" element={<Graph />} />
          <Route path="/incidents/:incidentId/cascade" element={<Cascade />} />
          <Route path="/response" element={<Response />} />
          <Route path="/events" element={<Events />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/settings" element={<Settings />} />
          {/* The agent floor is reachable at both the console path and the /app prefix. */}
          <Route path="/kitchen" element={<Kitchen />} />
          <Route path="/app/kitchen" element={<Kitchen />} />
          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Routes>
      </AnimatePresence>
    </Shell>
  );
}