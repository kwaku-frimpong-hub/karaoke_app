import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'

import HostAuthScreen from './features/host/HostAuthScreen'
import HostDashboardScreen from './features/host/HostDashboardScreen'
import HostHomeScreen from './features/host/HostHomeScreen'
import JoinScreen from './features/join/JoinScreen'
import QueueScreen from './features/queue/QueueScreen'
import SubmitSongScreen from './features/submit/SubmitSongScreen'
import './App.css'

function ScanLanding() {
  return (
    <div className="screen">
      <h1>Friday Karaoke</h1>
      <p className="muted">
        Scan the QR code on the screen to join tonight&rsquo;s karaoke.
      </p>
      <p>
        <Link to="/host">Host? Sign in</Link>
      </p>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/join" replace />} />
        <Route path="/join" element={<ScanLanding />} />
        <Route path="/join/:joinCode" element={<JoinScreen />} />
        <Route path="/join/:joinCode/queue" element={<QueueScreen />} />
        <Route path="/join/:joinCode/submit" element={<SubmitSongScreen />} />
        <Route path="/host/login" element={<HostAuthScreen />} />
        <Route path="/host" element={<HostHomeScreen />} />
        <Route path="/host/sessions/:sessionId" element={<HostDashboardScreen />} />
        <Route path="*" element={<Navigate to="/join" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
