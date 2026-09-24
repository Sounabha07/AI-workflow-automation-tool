import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { TopBar } from "@/components/TopBar";
import { WorkflowsPage } from "@/pages/WorkflowsPage";
import { HistoryPage } from "@/pages/HistoryPage";
import { EditorPage } from "@/pages/EditorPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen flex-col bg-canvas">
      <TopBar />
      <main className="min-h-0 flex-1">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <BrowserRouter>
          <Routes>
            <Route
              path="/"
              element={
                <Layout>
                  <WorkflowsPage />
                </Layout>
              }
            />
            <Route
              path="/history"
              element={
                <Layout>
                  <HistoryPage />
                </Layout>
              }
            />
            <Route
              path="/workflows/:id"
              element={
                <Layout>
                  <EditorPage />
                </Layout>
              }
            />
            <Route
              path="/workflows/:id/runs/:runId"
              element={
                <Layout>
                  <EditorPage />
                </Layout>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster position="top-center" richColors closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
