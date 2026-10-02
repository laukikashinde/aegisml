import React from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Incidents from './pages/Incidents'
import IncidentDetail from './pages/IncidentDetail'
import Models from './pages/Models'
import Monitoring from './pages/Monitoring'
import Deployments from './pages/Deployments'
import Pipelines from './pages/Pipelines'
import Approvals from './pages/Approvals'
import AuditLog from './pages/AuditLog'
import Simulations from './pages/Simulations'
import Experiments from './pages/Experiments'

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-slate-50">
        <Sidebar />
        <main className="flex-1 min-w-0 overflow-y-auto">
          <Routes>
            <Route path="/"               element={<Dashboard />} />
            <Route path="/incidents"      element={<Incidents />} />
            <Route path="/incidents/:id"  element={<IncidentDetail />} />
            <Route path="/models"         element={<Models />} />
            <Route path="/monitoring"     element={<Monitoring />} />
            <Route path="/deployments"    element={<Deployments />} />
            <Route path="/pipelines"      element={<Pipelines />} />
            <Route path="/approvals"      element={<Approvals />} />
            <Route path="/experiments"    element={<Experiments />} />
            <Route path="/simulations"    element={<Simulations />} />
            <Route path="/audit"          element={<AuditLog />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
