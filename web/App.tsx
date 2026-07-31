import React from "react";
import { ProductCatalogPage } from "./ProductCatalogPage";
import { WorkspacePage } from "./WorkspacePage";

export const App: React.FC = () => {
  const workspaceId = new URLSearchParams(window.location.search).get("workspace")?.trim();
  const view = new URLSearchParams(window.location.search).get("view")?.trim();

  return (
    <div className="app-shell">
      <header className="top-nav">
        <a className="top-nav__brand" href="/web">
          ActuaryPOC
        </a>
        <div className="top-nav__subtitle">Product Understanding Workspaces</div>
      </header>
      <main className="app-shell__main">
        {workspaceId ? <WorkspacePage workspaceId={workspaceId} view={view} /> : <ProductCatalogPage />}
      </main>
    </div>
  );
};
