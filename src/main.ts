import "./style.css";
import { startDrill } from "./drill.ts";
import type { Drill } from "./types.ts";

const app = document.querySelector<HTMLDivElement>("#app");

const fail = (msg: string): void => {
  if (app) {
    app.innerHTML = `<div class="empty"><h1>Approach Trainer</h1><p>${msg}</p></div>`;
  }
};

const main = async (): Promise<void> => {
  if (!app) {
    return;
  }
  try {
    const res = await fetch("clips/manifest.json");
    if (!res.ok) {
      throw new Error(`manifest ${res.status}`);
    }
    const drills = (await res.json()) as Drill[];
    if (drills.length === 0) {
      fail("No clips yet. Run the pipeline to build clips/manifest.json.");
      return;
    }
    startDrill(drills, app);
  } catch (error) {
    fail(`Couldn't load clips: ${String(error)}`);
  }
};

void main();
