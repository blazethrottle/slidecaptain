import { useState } from "react";
import type { ProjectInfo } from "./api/client";
import { ProjectList } from "./screens/ProjectList";
import { ProjectView } from "./screens/ProjectView";

export function App() {
  const [current, setCurrent] = useState<ProjectInfo | null>(null);
  if (current === null) return <ProjectList onOpen={setCurrent} />;
  return <ProjectView project={current} onBack={() => setCurrent(null)} />;
}
