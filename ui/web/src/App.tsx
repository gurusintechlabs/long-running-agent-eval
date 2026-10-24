import { BrowserRouter } from "react-router-dom";
import { AuthGate } from "./app/AuthGate";
import { DataVersionProvider } from "./app/DataVersion";
import { AppRoutes } from "./routes";

export function App() {
  return (
    <AuthGate>
      <DataVersionProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </DataVersionProvider>
    </AuthGate>
  );
}
