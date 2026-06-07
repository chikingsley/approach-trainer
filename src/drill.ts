import type { Drill } from "./types.ts";

const STORAGE_KEY = "approach-trainer:progress";

type Progress = Record<string, { lastRating: number | null; seen: number }>;

const loadProgress = (): Progress => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Progress;
  } catch {
    return {};
  }
};

const saveProgress = (p: Progress): void => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
};

const shuffle = <T>(items: readonly T[]): T[] => {
  const arr = [...items];
  for (let i = arr.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j] as T, arr[i] as T];
  }
  return arr;
};

class DrillSession {
  private readonly order: Drill[];
  private readonly root: HTMLElement;
  private idx = 0;
  private progress: Progress;
  private revealed = false;

  constructor(drills: readonly Drill[], root: HTMLElement) {
    this.root = root;
    this.progress = loadProgress();
    this.order = shuffle(drills);
  }

  mount(): void {
    this.render();
  }

  async revealCurrent(): Promise<void> {
    this.revealed = true;
    this.render();
    const video = this.root.querySelector("video");
    if (video) {
      video.currentTime = 0;
      try {
        await video.play();
      } catch {
        /* autoplay can be blocked; controls are shown */
      }
    }
  }

  private get current(): Drill {
    return this.order[this.idx] as Drill;
  }

  private next(): void {
    this.idx = (this.idx + 1) % this.order.length;
    this.revealed = false;
    this.render();
  }

  private rate(score: number): void {
    const d = this.current;
    const prev = this.progress[d.id] ?? { lastRating: null, seen: 0 };
    this.progress[d.id] = { lastRating: score, seen: prev.seen + 1 };
    saveProgress(this.progress);
    this.next();
  }

  private render(): void {
    const d = this.current;
    const seen = this.progress[d.id]?.seen ?? 0;
    const poster = `clips/frames/${d.id}.jpg`;
    const people =
      d.num_speakers === 1 ? "1 person" : `${d.num_speakers} people`;

    this.root.innerHTML = `
      <header class="bar">
        <span class="brand">Approach Trainer</span>
        <span class="counter">${this.idx + 1} / ${this.order.length}</span>
      </header>

      <main class="stage">
        <div class="scene">
          <video
            playsinline
            preload="metadata"
            poster="${poster}"
            ${this.revealed ? "controls" : ""}
            src="${d.file}#t=0"
          ></video>
          ${this.revealed ? "" : '<div class="scrim"><span>What do you say?</span></div>'}
        </div>

        <div class="meta">
          <span class="who">${d.approacher}</span>
          <span class="dot">·</span>
          <span>${people}</span>
          ${seen > 0 ? `<span class="dot">·</span><span class="seen">seen ${seen}×</span>` : ""}
        </div>

        ${this.revealed ? DrillSession.revealMarkup(d) : DrillSession.promptMarkup()}
      </main>
    `;

    this.bind();
  }

  private static revealMarkup(d: Drill): string {
    return `
      <div class="reveal">
        <p class="label">His opener</p>
        <p class="opener">${d.opener}</p>
        <details class="transcript">
          <summary>Full exchange</summary>
          <p>${d.full_transcript}</p>
        </details>
      </div>
      <div class="actions">
        <p class="rate-label">How was your line vs. his?</p>
        <div class="ratings">
          <button data-rate="1" type="button">Whiffed</button>
          <button data-rate="2" type="button">Okay</button>
          <button data-rate="3" type="button">Solid</button>
          <button data-rate="4" type="button">Better than his</button>
        </div>
      </div>
    `;
  }

  private static promptMarkup(): string {
    return `
      <div class="actions">
        <button class="primary" data-action="reveal" type="button">
          Reveal his line ↵
        </button>
        <button class="ghost" data-action="skip" type="button">Skip</button>
      </div>
    `;
  }

  private bind(): void {
    this.root
      .querySelector('[data-action="reveal"]')
      ?.addEventListener("click", () => {
        void this.revealCurrent();
      });
    this.root
      .querySelector('[data-action="skip"]')
      ?.addEventListener("click", () => this.next());
    for (const btn of this.root.querySelectorAll<HTMLButtonElement>(
      "[data-rate]"
    )) {
      btn.addEventListener("click", () => this.rate(Number(btn.dataset.rate)));
    }
  }
}

export const startDrill = (
  drills: readonly Drill[],
  root: HTMLElement
): void => {
  const session = new DrillSession(drills, root);
  session.mount();
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      const reveal = root.querySelector<HTMLButtonElement>(
        '[data-action="reveal"]'
      );
      if (reveal) {
        e.preventDefault();
        reveal.click();
      }
    }
  });
};
