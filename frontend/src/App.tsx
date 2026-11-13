import { useEffect, useState } from "react";
import Intake from "./pages/Intake";
import Review from "./pages/Review";
import Handover from "./pages/Handover";

export function navigate(to: string): void {
  if (window.location.pathname !== to) {
    window.history.pushState({}, "", to);
  }
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0, behavior: "auto" });
}

function usePathname(): string {
  const [pathname, setPathname] = useState(window.location.pathname);
  useEffect(() => {
    const onPop = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  return pathname;
}

export default function App() {
  const pathname = usePathname();
  const parts = pathname.split("/").filter(Boolean);

  if (parts[0] === "review" && parts[1]) {
    return <Review sessionId={decodeURIComponent(parts[1])} />;
  }
  if (parts[0] === "handover" && parts[1]) {
    return <Handover token={decodeURIComponent(parts[1])} />;
  }
  return <Intake />;
}
