import { useState } from "react";
import type { ProjectInfo } from "./api/client";
import { ProjectList } from "./screens/ProjectList";

export function App() {
  const [current, setCurrent] = useState<ProjectInfo | null>(null);
  if (current === null) return <ProjectList onOpen={setCurrent} />;
  return (
    <main>
      <button onClick={() => setCurrent(null)}>목록으로</button>
      <h1>{current.title}</h1>
    </main>
  );
}
